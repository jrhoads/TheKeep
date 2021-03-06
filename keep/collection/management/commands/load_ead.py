from optparse import make_option
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from eulexistdb.exceptions import DoesNotExist, ReturnedMultiple
from keep.common.fedora import Repository
from keep.collection.models import CollectionObject, FindingAid

class Command(BaseCommand):
    '''Create :class:`~keep.collection.models.CollectionObject` objects
    based on corresponding :class:`~keep.collection.models.FindingAid` EAD.

    Takes the PID for the numbering scheme object that the collections should
    belong to (will be used to ensure the correct document is found when searching
    for EAD, and created collections will belong to the specified numbering scheme
    object).  Also takes a list of collection ids; for each id specified, this script
    will look for the corresponding EAD document within the requested numbering
    scheme and generate a new :class:`~keep.collection.models.CollectionObject`.
    '''
    help = '''Create a new collection based on a Finding Aid EAD document.
Takes a pid or pid alias for the archive the new collection will belong to
and the collection number, which are used to find the appropriate Finding Aid
document.  Can also take a list of multiple collection numbers.  Example use:

    load_ead marbl 488 1000

'''
    args = 'num-scheme-pid collection-id [...]'

    option_list = BaseCommand.option_list + (
        make_option('--dry-run', '-n',
            dest='dryrun',
            action='store_true',
            help="Report what would be done, but don't ingest any Fedora objects."),
        )

    def handle(self, numbering_pid, *ids, **options):
        verbosity = int(options['verbosity'])

        numbering = self.get_numbering(numbering_pid)
        if not numbering.exists:
            raise CommandError('Numbering scheme %s not found' % (numbering_pid,))
        numbering_title = numbering.mods.content.title

        created = 0
        errors = 0

        for id in ids:
            # check for existing collection before creating new
            existing_coll = list(CollectionObject.
                                 find_by_collection_number(id, numbering.pid))
            if existing_coll:
                print 'Collection %s already exists as %s' % \
                      (id, ', '.join([coll.pid for coll in existing_coll]))
                continue

            coll = None
            try:
                fa = FindingAid.find_by_unitid(id, numbering_title)
                coll = fa.generate_collection()
                # new collection parent collection is the archive collection object
                coll.collection = numbering
                if not options['dryrun']:
                    coll.save()
                if verbosity:
                    print 'Added %s for collection %s: %s (from %s)' % (coll, id, coll.mods.content.title, numbering_title)
                created += 1
            except DoesNotExist:
                print 'No EAD found for id %s in %s' % (id, numbering_title)
                errors += 1
            except ReturnedMultiple:
                print 'Multiple EADs found for id %s in %s' % (id, numbering_title)
                errors += 1
            except:
                if coll is not None:
                    print 'Failed to save %s for collection %s: %s (from %s)' %  (coll, id, coll.mods.content.title, numbering_title)
                raise

        if verbosity > 1:
            print '%d records created' % (created,)
            print '%d records failed' % (errors,)

    def get_numbering(self, pid):
        if pid in settings.PID_ALIASES:
            pid = settings.PID_ALIASES[pid]
        repo = Repository()
        return repo.get_object(pid, type=CollectionObject)

