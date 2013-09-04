'''
View methods for creating, editing, searching, and browsing
:class:`~keep.collection.models.CollectionObject` instances in Fedora.
'''
import logging

from django.contrib.admin.views.decorators import staff_member_required

from rdflib.namespace import RDF

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.core.serializers.json import DjangoJSONEncoder
from django.core.urlresolvers import reverse
from django.http import Http404, HttpResponse
from django.shortcuts import render

from eulcommon.djangoextras.http import HttpResponseSeeOtherRedirect
from eulfedora.views import raw_datastream, raw_audit_trail
from eulcommon.searchutil import search_terms
from eulfedora.util import RequestFailed

from keep.collection.forms import CollectionForm, CollectionSearch, SimpleCollectionEditForm
from keep.collection.models import CollectionObject, SimpleCollection
from keep.collection.tasks import queue_batch_status_update
from keep.common.fedora import Repository, history_view
from keep.common.rdfns import REPO
from keep.common.utils import solr_interface


logger = logging.getLogger(__name__)

json_serializer = DjangoJSONEncoder(ensure_ascii=False, indent=2)


@permission_required("common.marbl_allowed")
def view(request, pid):
    '''View a single :class:`~keep.collection.models.CollectionObject`.
    Not yet implemented; for now, redirects to :meth:`edit` view.
    '''
    # this view isn't implemented yet, but we want to be able to use the
    # uri. so if someone requests the uri, send them straight to the edit
    # page for now.
    return HttpResponseSeeOtherRedirect(reverse('collection:edit',
                kwargs={'pid': pid}))


@permission_required("common.marbl_allowed")
def edit(request, pid=None):
    '''Create a new or edit an existing Fedora
    :class:`~keep.collection.models.CollectionObject`.  If a pid is
    specified, attempts to retrieve an existing object.  Otherwise, creates a new one.
    '''
    repo = Repository(request=request)
    try:
        # get collection object - existing if pid specified, or new if not
        obj = repo.get_object(type=CollectionObject, pid=pid)
        # NOTE: on new objects, for now, this will generate and throw away pids
        # TODO: solve this in eulfedora before we start using ARKs for pids

        if request.method == 'POST':
            # if data has been submitted, initialize form with request data and object mods
            form = CollectionForm(request.POST, instance=obj)
            if form.is_valid():     # includes schema validation
                form.update_instance()  # update instance MODS & RELS-EXT (possibly redundant)
                if pid is None:
                    # new object
                    action = 'created'
                else:
                    # existing object
                    action = 'updated'

                if 'comment' in form.cleaned_data and form.cleaned_data['comment']:
                    comment = form.cleaned_data['comment']
                else:
                    comment = 'updating metadata'

                # NOTE: by sending a log message, we force Fedora to store an
                # audit trail entry for object creation, which doesn't happen otherwise
                obj.save(comment)
                messages.success(request, 'Successfully %s collection <a href="%s">%s</a>' % \
                        (action, reverse('collection:edit', args=[obj.pid]), obj.pid))

                # form submitted via normal save button - redirect to main audio page
                if '_save_continue' not in request.POST:
                    return HttpResponseSeeOtherRedirect(reverse('site-index'))

                # otherwise, form was submitted via "save and continue editing"
                else:
                    # creating a new object- redirect to the edit-collection url for the new pid
                    if pid is None:
                        return HttpResponseSeeOtherRedirect(reverse('collection:edit',
                                                            args=[obj.pid]))

                    # if form was valid & object was saved but user has requested
                    # "save & continue editing" re-init the form so that formsets
                    # will display correctly
                    else:
                        form = CollectionForm(instance=obj)

            # form was posted but not valid
            else:
                # if we attempted to save and failed, add a message since the error
                # may not be obvious or visible in the first screenful of the form
                messages.error(request,
                    '''Your changes were not saved due to a validation error.
                    Please correct any required or invalid fields indicated below and save again.''')

            # in any other case - fall through to display edit form again
        else:
            # GET - display the form for editing
            # FIXME: special fields not getting set!
            form = CollectionForm(instance=obj)

    except RequestFailed as e:
        # if there was an error accessing the object raise http404
        # or the object does not exist, raise a 404
        # NOTE: this will 404 for any object where current credentials
        # do not allow user to access object info (i.e., insufficient
        # permissions to even know whether or not the object exists)
        if not obj.exists or e.code == 404:
            raise Http404
        # otherwise, re-raise and handle as a common fedora connection error
        else:
            raise

    context = {'form': form}
    if pid is not None:
        context['collection'] = obj

    return render(request, 'collection/edit.html', context)


def history(request, pid):
    return history_view(request, pid, type=CollectionObject,
                        template_name='collection/history.html')


@staff_member_required
def search(request):
    '''Search for :class:`~keep.collection.models.CollectionObject`
    instances.
    '''
    form = CollectionSearch(request.GET, prefix='collection')
    context = {'search': form}
    if form.is_valid():
        # include all non-blank fields from the form as search terms
        search_opts = dict((key, val)
                           for key, val in form.cleaned_data.iteritems()
                           if val is not None and val != '')  # but need to search by 0
        # restrict to currently configured pidspace and collection content model
        search_opts.update({
            'pid': '%s:*' % settings.FEDORA_PIDSPACE,
            'content_model': CollectionObject.COLLECTION_CONTENT_MODEL,
            })

        # collect non-empty, non-default search terms to display to user on results page
        search_info = {}
        for field, val in form.cleaned_data.iteritems():
            key = form.fields[field].label  # use form display label
            if key is None:     # if field label is not set, use field name as a fall-back
                key = field

            if val is not None and val != '':     # if search value is not empty, selectively add it
                if hasattr(val, 'lstrip'):  # solr strings can't start with wildcards
                    extra_solr_cleaned = val.lstrip('*?')
                    if val != extra_solr_cleaned:
                        if not extra_solr_cleaned:
                            messages.info(request, 'Ignoring search term "%s": Text fields can\'t start with wildcards.' % (val,))
                            del search_opts[field]
                            continue
                        messages.info(request, 'Searching for "%s" instead of "%s": Text fields can\'t start with wildcards.' %
                                      (extra_solr_cleaned, val))
                        val = extra_solr_cleaned
                        search_opts[field] = val

                if field == 'archive_id':       # for archive, get  info
                    search_info[key] = CollectionObject.find_by_pid(val)
                elif val != form.fields[field].initial:     # ignore default values
                    search_info[key] = val
        context['search_info'] = search_info

        solr = solr_interface()
        solrquery = solr.query(**search_opts).sort_by('source_id')
        # TODO: eventually, we'll need proper pagination here;
        # for now, set a large max to return everything
        context['results'] = solrquery.paginate(start=0, rows=1000).execute()

    # if the form was not valid, set the current instance of the form
    # as the sidebar form instance to display the error
    else:
        context['collection_search'] = form

    # render search results page; if there was an error, results will be displayed as empty
    return render(request, 'collection/search.html', context)


@permission_required("common.marbl_allowed")
def browse(request):
    '''Browse :class:`~keep.collection.models.CollectionObject` by
    hierarchy, grouped by archive.
    '''
    ## search opts unused?!
    # search_opts = {
    #     'pid': '%s:*' % settings.FEDORA_PIDSPACE,
    #     'content_model': CollectionObject.COLLECTION_CONTENT_MODEL,
    # }
    collections = CollectionObject.item_collections()
    # sort by archive, then by source id (collection number)
    display_colls = sorted(collections,
                           key=lambda c: (c['archive_id'], c.get('source_id', None)))
    return render(request, 'collection/browse.html', {'collections': display_colls})


@permission_required("common.marbl_allowed")
def view_datastream(request, pid, dsid):
    'Access raw object datastreams (MODS, RELS-EXT, DC)'
    # initialize local repo with logged-in user credentials & call generic view
    return raw_datastream(request, pid, dsid, type=CollectionObject, repo=Repository(request=request))


@permission_required("common.marbl_allowed")
def view_audit_trail(request, pid):
    'Access XML audit trail for a collection object'
    # initialize local repo with logged-in user credentials & call eulfedora view
    # FIXME: redundant across collection/arrangement/audio apps; consolidate?
    return raw_audit_trail(request, pid, type=CollectionObject,
                           repo=Repository(request=request))


@permission_required("common.arrangement_allowed")
def simple_edit(request, pid=None):
    ''' Edit an existing Fedora
    :class:`~keep.collection.models.SimpleCollection`.  If a pid is
    specified, attempts to retrieve an existing object.
    '''
    repo = Repository(request=request)

    try:
        obj = repo.get_object(pid=pid, type=SimpleCollection)

        if request.method == 'POST':
            form = SimpleCollectionEditForm(request.POST)
            if form.is_valid():
                status = form.cleaned_data['status']


                if status == obj.mods.content.restrictions_on_access.text:
                    # don't queue job if there is no change
                    messages.info(request, 'Status is unchanged')

                else:
                    # queue celery task to update items in this batch
                    queue_batch_status_update(obj, status)
                    messages.info(
                        request,
                        'Batch status update has been queued; ' +
                        'please check later via <a href="%s">recent tasks</a> page' %
                        reverse('tasks:recent')
                    )

        else:
            #Just Display the form
            form = SimpleCollectionEditForm(initial={'status': obj.mods.content.restrictions_on_access.text})

    except RequestFailed, e:
        # if there was a 404 accessing objects, raise http404
        # NOTE: this probably doesn't distinguish between object exists with
        # no MODS and object does not exist at all
        if e.code == 404:
            raise Http404
        # otherwise, re-raise and handle as a common fedora connection error
        else:
            raise

    context = {'form': form}
    if pid is not None:
        context['obj'] = obj

    return render(request, 'collection/simple_edit.html', context)


#find objects with a particular type specified  in the rels-ext and return them as
def _objects_by_type(type_uri, type=None):
    """
    Returns a list of objects with the specified type_uri as objects of the specified type
    :param type_uri: The uri of the type being searched
    :param type: The type of object that should be returned
    """
    repo = Repository()

    pids = repo.risearch.get_subjects(RDF.type, type_uri)
    pids_list = list(pids)

    for pid in pids_list:
        yield repo.get_object(pid=pid, type=type)


@permission_required("common.arrangement_allowed")
def simple_browse(request):
    response_code = None
    context = {}
    try:
        objs = _objects_by_type(REPO.SimpleCollection, SimpleCollection)
        objs = sorted(objs, key=lambda s: s.label)
        context['objs'] = objs
    except RequestFailed:
        response_code = 500
        # FIXME: this is duplicate logic from generic search view
        context['server_error'] = 'There was an error ' + \
            'contacting the digital repository. This ' + \
            'prevented us from completing your search. If ' + \
            'this problem persists, please alert the ' + \
            'repository administrator.'

    response = render(request, 'collection/simple_browse.html', context)
    if response_code is not None:
        response.status_code = response_code
    return response


@permission_required("common.marbl_allowed")
def collection_suggest(request):
    '''Suggest view for collections, for use with use with `JQuery UI
    Autocomplete`_ widget.  Searches for collections on all of the
    terms passed in (as multiple keywords), similar to the way the
    combined search works.

    .. _JQuery UI Autocomplete: http://jqueryui.com/demos/autocomplete/

    :param request: the http request passed to the original view
        method (used to retrieve the search term)
    '''
    term = request.GET.get('term', '')

    suggestions = []

    if term:
        # If the search term doesn't end in space, add a wildcard to
        # the last word to allow for partial word matching.
        if term[-1] != ' ':
            term += '*'
        terms = search_terms(term)

        solr = solr_interface()
        # common query parameters and options
        base_query = solr.query() \
                    .filter(content_model=CollectionObject.COLLECTION_CONTENT_MODEL) \
                    .field_limit(['pid', 'source_id', 'title', 'archive_short_name',
                                  'creator']) \
                    .sort_by('-score')

        q = base_query.query(terms)

        # NOTE: there seems to be a Lucene/Solr bug/quirk where adding
        # a wildcard at the end of a word causes Solr not to match the
        # exact word (even though docs indicate this should work).
        # As a work-around, if we added a * and got 0 results,
        # try the search again without the wildcard.
        if term[-1] == '*' and q.count() == 0:
            q = base_query.query(search_terms(term[:-1]))

        suggestions = [{'label': '%s %s' % (c.get('source_id', ''),
                                            c.get('title', '(no title')),
                        'value': c['pid'],  # FIXME: do we need URI here?
                        'category':c.get('archive_short_name', ''),
                        'desc': c.get('creator', '')}
                       for c in q[:15]]

    return HttpResponse(json_serializer.encode(suggestions),
                         mimetype='application/json')
