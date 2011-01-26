import logging
import os
import tempfile
import magic

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.core.paginator import Paginator
from django.core.urlresolvers import reverse
from django.http import HttpResponse, Http404, HttpResponseForbidden, HttpResponseBadRequest
from django.shortcuts import render_to_response
from django.template import RequestContext
from django.template.defaultfilters import slugify

from eulcore.django.http import HttpResponseSeeOtherRedirect
from eulcore.django.taskresult.models import TaskResult
from eulcore.fedora.util import RequestFailed, PermissionDenied
from eulcore.fedora.models import DigitalObjectSaveFailure

from keep.audio import forms as audioforms
from keep.audio.models import AudioObject
from keep.audio.tasks import convert_wav_to_mp3
from keep.common.fedora import Repository
from keep.common.utils import md5sum

allowed_audio_types = ['audio/x-wav', 'audio/wav']

@permission_required('is_staff')  # sets ?next=/audio/ but does not return back here
def index(request):
    search = audioforms.ItemSearch()
    return render_to_response('audio/index.html', {'search' : search},
            context_instance=RequestContext(request))

@permission_required('is_staff')
def upload(request):
    '''Upload file(s) and create new fedora :class:`~keep.audio.models.AudioObject` (s).
    Only accepts audio/x-wav currently.
    
    There are two distinct ways to upload file. The first case is kicked off when "fileManualUpload"
    exists in the posted form. If it does, then this was not a HTML5 browser, and the file upload
    occurs as is usual for a single file upload.

    In the other approach, the file was uploaded via a HTML5 ajax upload already. In this case, we
    are reading in various hidden generated form fields that indicate what was uploaded from the 
    javascript code.
    '''

    ctx_dict = {}
    response_code = None

    if request.method == 'POST':
        #See if it is manual upload due to non-HTML5 browser.
        if request.FILES.has_key('fileManualUpload'):
            uploaded_file = request.FILES['fileManualUpload']
            m = magic.Magic(mime=True)
            type = m.from_file(uploaded_file.temporary_file_path())
            
            if ';' in type:
                type, charset = type.split(';')
            if type not in allowed_audio_types:
                messages.error(request, 'The file uploaded is not of an accepted type (got %s)' % type)
            else:
                try:
                    # TODO: consolidate common logic for single & multiple file ingest
                    # initialize from the file itself; use original name as initial object label
                    obj = AudioObject.init_from_file(uploaded_file.temporary_file_path(),
                                                     uploaded_file.name, request,
                                                     md5sum(uploaded_file.temporary_file_path()))
                    obj.save()
                    #Start the task to convert the WAV audio to a compressed format.
                    result = convert_wav_to_mp3.delay(obj.pid,
                            existingFilePath=uploaded_file.temporary_file_path())
                    task = TaskResult(label='Generate MP3', object_id=obj.pid,
                        url=obj.get_absolute_url(), task_id=result.task_id)
                    task.save()

                    messages.success(request, 'Successfully ingested file %s in fedora as %s.'
                            % (uploaded_file.name, obj.pid))
                except Exception as e:
                    response_code = 500
                    ctx_dict['server_error'] = 'There was an error ' + \
                            'contacting the digital repository. This ' + \
                            'prevented us from ingesting your file. If ' + \
                            'this problem persists, please alert the ' + \
                            'repository administrator.'
                    response = render_to_response('audio/uploadForm.html', ctx_dict,context_instance=RequestContext(request))
                    if response_code is not None:
                        response.status_code = response_code
                    return response
                    
        #Process the list of files.
        elif request.POST.has_key('fileUploads'):

            file_list = request.POST.getlist('fileUploads')
            file_original_name_list = request.POST.getlist('originalFileNames')
            file_md5sum_list = request.POST.getlist('fileMD5sum')

            if len(file_list) != len(file_original_name_list) != len(file_md5sum_list):
                messages.error(request, 'The hidden input file lists length did not match... some type of form error')
            else:
                for index in range(len(file_list)):
                    #Add the full path qualifier of the temp directory from settings.
                    fullFilePath = os.path.join(settings.INGEST_STAGING_TEMP_DIR,file_list[index])
                    
                    # check mimetype of uploaded file (uploaded_file.content_type is unreliable)
                    m = magic.Magic(mime=True)
                    type = m.from_file(fullFilePath)
                    del m
                    if ';' in type:
                        type, charset = type.split(';')
                    if type not in allowed_audio_types:
                        messages.error(request, 'The file %s is not of an accepted type (got %s)' % (file_original_name_list[index], type))
                    #type is allowed
                    else:
                        #recheck md5sum once more before ingesting....
                        if file_md5sum_list[index] != md5sum(fullFilePath):
                            messages.error(request, 'The file %s has a corrupted MD5 sum on the server.' % file_original_name_list[index])
                        else:
                            #fedora inject code to go here....
                            try:
                                 # initialize from the file itself; use original name as initial object label
                                obj = AudioObject.init_from_file(fullFilePath,
                                                     file_original_name_list[index], 
                                                     request,
                                                     file_md5sum_list[index])
                                obj.save()
                                #Start the task to convert the WAV audio to a compressed format. This task will also delete
                                #the existing file upon completion.
                                result = convert_wav_to_mp3.delay(obj.pid,existingFilePath=fullFilePath)
                                task = TaskResult(label='Generate MP3', object_id=obj.pid,
                                    url=obj.get_absolute_url(), task_id=result.task_id)
                                task.save()
                                messages.success(request, 'Successfully ingested file %s in fedora as %s.'
                                                % (file_original_name_list[index], obj.pid))
                            except Exception as e:
                                logging.debug(e)
                                messages.error(request, 'Failed to ingest file %s in fedora (fedora is either down or the checksum is incorrect).'
                                               % (file_original_name_list[index]))
                        
        #Return the response with the messages for both cases above.
        return HttpResponseSeeOtherRedirect(reverse('audio:index'))

    #non-posted form
    else:
        ctx_dict['allowed_audio_types'] = allowed_audio_types
        ctx_dict['action_page'] = reverse('audio:HTML5FileUpload')

    response = render_to_response('audio/uploadForm.html', ctx_dict,
                                  context_instance=RequestContext(request))
    if response_code is not None:
        response.status_code = response_code
    return response

@permission_required('is_staff')
def HTML5FileUpload(request):
    '''Used for the AJAX HTML5 upload only. Accepts the AJAX request, checks the
    request, uploads the file, returns its end name.'''
    
    #Setup the directory for the file upload.
    dir = settings.INGEST_STAGING_TEMP_DIR
    if not os.path.exists(dir):
        os.makedirs(dir)
    
    #Get the header values.
    try:
        fileName = request.META['HTTP_X_FILE_NAME']
        fileMD5 = request.META['HTTP_X_FILE_MD5']
    except Exception as e:
        return HttpResponseBadRequest('Error - missing needed headers (either HTTP-X-FILE-NAME or HTTP-X-FILE-MD5).')
    
    #Returns a Tuple with: "<file_base>", ".", and "<file_extension>"
    fileDetailsTuple = fileName.rpartition('.')
    fileBase = fileDetailsTuple[0]
    fileDot = fileDetailsTuple[1]
    fileExtension = fileDetailsTuple[2]
    
    #returnedMkStemp is a tuple with the name in the 2nd position.
    returnedMkStemp = tempfile.mkstemp(fileDot+fileExtension,fileBase+"_",dir)
    
    destination = open(returnedMkStemp[1], 'wb+')
    destination.write(request.raw_post_data)
    destination.close()
    
    newFileName = os.path.basename(returnedMkStemp[1])
    
    try:
        os.close(returnedMkStemp[0])
        m = magic.Magic(mime=True)
        type = m.from_file(returnedMkStemp[1])

        del m
        if ';' in type:
            type, charset = type.split(';')
        if type not in allowed_audio_types:
            os.remove(returnedMkStemp[1])
            #return HttpResonse('alert(The type ' + type + ' of file ' + fileName + ' is not allowed. That file was rejected.); $("item' + request.META['HTTP_X_FILE_INDEX'] + '").remove();')
            return HttpResponseBadRequest('Error - Incorrect File Type')
    except Exception as e:
        logging.debug(e)
        
    #Check the MD5 sum.
    try:
        if md5sum(returnedMkStemp[1]) != fileMD5:
            return HttpResponseBadRequest('Error - MD5 Did Not Match')
    except Exception as e:
        logging.debug(e)

    return HttpResponse(newFileName)
    
@permission_required('is_staff')
def search(request):
    '''Search for  :class:`~keep.audio.models.AudioObject` by pid,
    title, description, collection, date, or rights.'''
    response_code = None
    form = audioforms.ItemSearch(request.GET, prefix='audio')
    ctx_dict = {'search': form}
    if form.is_valid():
        search_opts = {
            'type': AudioObject,
            # restrict to objects in configured pidspace
            'pid__contains': '%s*' % settings.FEDORA_PIDSPACE,
            # restrict by cmodel in dc:format
            'format__contains': AudioObject.AUDIO_CONTENT_MODEL,
        }
        if form.cleaned_data['pid']:
            search_opts['pid__contains'] = '%s' % form.cleaned_data['pid']
            # add a wildcard if the search pid is the initial value
            if form.cleaned_data['pid'] == form.fields['pid'].initial:
                search_opts['pid__contains'] += '*'
        if form.cleaned_data['title']:
            search_opts['title__contains'] = form.cleaned_data['title']
        if form.cleaned_data['description']:
            search_opts['description__contains'] = form.cleaned_data['description']
        if form.cleaned_data['collection']:
            search_opts['relation__contains'] = form.cleaned_data['collection']
        if form.cleaned_data['date']:
            search_opts['date__contains'] = form.cleaned_data['date']
        if form.cleaned_data['rights']:
            search_opts['rights__contains'] = form.cleaned_data['rights']
        
        if search_opts:
            # If they didn't specify any search options, don't bother
            # searching.
            try:
                repo = Repository(request=request)
                found = repo.find_objects(**search_opts)
                paginator = Paginator(list(found), 30)

                try:
                    page = int(request.GET.get('page', '1'))
                except ValueError:
                    page = 1
                try:
                    results = paginator.page(page)
                except (EmptyPage, InvalidPage):
                    results = paginator.page(paginator.num_pages)

                ctx_dict['results'] = results.object_list
                ctx_dict['page'] = results
                # pass search term query opts to view for pagination links
                ctx_dict['search_opts'] = request.GET.urlencode()
            except:
                response_code = 500
                ctx_dict['server_error'] = 'There was an error ' + \
                    'contacting the digital repository. This ' + \
                    'prevented us from completing your search. If ' + \
                    'this problem persists, please alert the ' + \
                    'repository administrator.'

    response = render_to_response('audio/search.html', ctx_dict,
                    context_instance=RequestContext(request))
    if response_code is not None:
        response.status_code = response_code
    return response

@permission_required('is_staff')
def view(request, pid):
    '''View a single :class:`~keep.audio.models.AudioObject`.
    Not yet implemented; for now, redirects to :meth:`edit` view.
    '''
    # this view isn't implemented yet, but we want to be able to use the
    # uri. so if someone requests the uri, send them straight to the edit
    # page for now.
    return HttpResponseSeeOtherRedirect(reverse('audio:edit',
                kwargs={'pid': pid}))

@permission_required('is_staff')
def raw_datastream(request, pid, dsid):
    'Access raw object datastreams (mods, rels-ext, dc, digitaltech, sourcetech)'
    repo = Repository(request=request)
    obj = repo.get_object(pid, type=AudioObject)
    dsid = dsid.replace('-', '_')   # convert url dsid to datastream variable form
    try:
        # NOTE: could test that pid is actually an AudioObject using
        # obj.has_requisite_content_models but that would mean
        # an extra API call for every datastream but RELS-EXT
        # Leaving out for now, for efficiency
        ds = getattr(obj, dsid)
        if ds.exists:
            return HttpResponse(ds.content.serialize(pretty=True), mimetype=ds.mimetype)
        else:
            raise Http404
    except RequestFailed as rf:
        # if not actually an AudioObject or if either the object
        # or the requested datastream doesn't exist, 404
        if rf.code == 404 or not obj.has_requisite_content_models or \
                not obj.exists or not obj.dsid.exists:
            raise Http404

        # for anything else, re-raise & let Django's default 500 logic handle it
        raise

@permission_required('is_staff')
def edit(request, pid):
    '''Edit the metadata for a single :class:`~keep.audio.models.AudioObject`.'''
    repo = Repository(request=request)
    obj = repo.get_object(pid, type=AudioObject)
    try:
        # if this is not actually an AudioObject, then 404 (object is not available at this url)
        if not obj.has_requisite_content_models:
            raise Http404
        
        if request.method == 'POST':
            # if data has been submitted, initialize form with request data and object mods
            form = audioforms.AudioObjectEditForm(request.POST, instance=obj)
            if form.is_valid():     # includes schema validation
                # update foxml object with MODS from the form
                form.update_instance()      # instance is reference to mods object
                if obj.mods.content.is_valid():
                    obj.save()
                    messages.success(request, 'Updated %s' % pid)
                    # save & continue functionality - same as collection edit
                    if '_save_continue' not in request.POST:
                        return HttpResponseSeeOtherRedirect(reverse('audio:index'))
                # otherwise - fall through to display edit form again
        else:
            # GET - display the form for editing, pre-populated with content from the object
            form = audioforms.AudioObjectEditForm(instance=obj)

        return render_to_response('audio/edit.html', {'obj' : obj, 'form': form },
            context_instance=RequestContext(request))

    except PermissionDenied:
        # Fedora may return a PermissionDenied error when accessing a datastream
        # where the datastream does not exist, object does not exist, or user
        # does not have permission to access the datastream

        # check that the object exists - if not, 404        
        if not obj.exists:
            raise Http404
        # for now, assuming that if object exists and has correct content models,
        # it will have all the datastreams required for this view

        return HttpResponseForbidden('Permission Denied to access %s' % pid,
                                     mimetype='text/plain')

    except RequestFailed as rf:
        # if fedora actually returned a 404, propagate it
        if rf.code == 404:
            raise Http404
        
        msg = 'There was an error contacting the digital repository. ' + \
              'This prevented us from accessing audio data. If this ' + \
              'problem persists, please alert the repository ' + \
              'administrator.'
        return HttpResponse(msg, mimetype='text/plain', status=500)
        
         
@permission_required('is_staff')
def download_audio(request, pid):
    "Serve out the audio datastream for the fedora object specified by pid."
    repo = Repository(request=request)
    obj = repo.get_object(pid, type=AudioObject)
    # NOTE: this will probably need some work to be able to handle large datastreams
    try:
        response = HttpResponse(obj.audio.content, mimetype=obj.audio.mimetype)
        response['Content-Disposition'] = "attachment; filename=%s.wav" % slugify(obj.label)
        return response
    except:
        msg = 'There was an error contacting the digital repository. ' + \
              'This prevented us from accessing audio data. If this ' + \
              'problem persists, please alert the repository ' + \
              'administrator.'
        return HttpResponse(msg, mimetype='text/plain', status=500)

# download audio must be accessed by kiosk - should be IP restricted at apache level
def download_compressed_audio(request, pid):
    "Serve out the compressed audio datastream for the fedora object specified by pid."
    try:
        repo = Repository(request=request)
        obj = repo.get_object(pid, type=AudioObject)
    
        #Check that the stream has been added.
        if(obj.compressed_audio.exists):
            # NOTE: this will probably need some work to be able to handle large datastreams
        
            response = HttpResponse(obj.compressed_audio.content, mimetype=obj.compressed_audio.mimetype)
            response['Content-Disposition'] = "attachment; filename=%s.mp3" % slugify(obj.label)
            return response
        #if the compressed stream has not been added, ie. it conversion not done.
        msg = '<div style="width:800px; font-size:16px;">The compressed audio stream does not currently exist. ' + \
                  'This likely means the the audio conversion process ' + \
                  'for this file is in progress or has failed. Please ' + \
                  'try again shortly, and if the problem persists, contact ' + \
                  'an adminstrator.<br /><br /> To return to the previous ' + \
                  'page, please <a href="javascript:history.go(-1);">[click here]</a>.</div>' 
        return HttpResponse(msg, mimetype='text/html', status=404)
    except:
        msg = 'There was an error contacting the digital repository. ' + \
              'This prevented us from accessing audio data. If this ' + \
              'problem persists, please alert the repository ' + \
              'administrator.'
        return HttpResponse(msg, mimetype='text/plain', status=500)

@permission_required('is_staff')
def feed_list(request):
    'List and link to all current iTunes podcast feeds based on number of objects/pages.'
    paginated_objects = Paginator(list(AudioObject.all()), settings.MAX_ITEMS_PER_PODCAST_FEED)
    return render_to_response('audio/feed_list.html', {
                'per_page': settings.MAX_ITEMS_PER_PODCAST_FEED,
                'pages': paginated_objects.page_range,
                }, context_instance=RequestContext(request))
