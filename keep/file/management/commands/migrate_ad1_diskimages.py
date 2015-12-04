'''
Manage command to ingest migration disk images and associate them
with the existing disk image object they replace.
'''
from collections import defaultdict
from copy import deepcopy
from datetime import date, datetime
from django.core.management.base import BaseCommand
from eulfedora.server import Repository
import glob
import os
import uuid

from keep.common.fedora import DuplicateContent
from keep.common.models import PremisObjectCharacteristics, PremisRelationship, \
    PremisEvent, PremisLinkingObject
from keep.file.models import DiskImage


class Command(BaseCommand):
    '''Ingest migrated disk images and associate with existing AD1 disk images.'''
    help = __doc__

    #: default verbosity level
    v_normal = 1

    def add_arguments(self, parser):
        # Positional arguments: required directory to pick up content
        parser.add_argument('directory',
            help='Path to directory containing bags with disk images')
        parser.add_argument('--pidspace', default='emory',
            help='Fedora pidspace to use when looking for original (default: %(default)s')
        parser.add_argument('--file-uris', default=False, action='store_true',
            help='Use file URIs (i.e., migrated content is in configured LARGE_FILE_STAGING_FEDORA_DIR')

    # metadata values for all migrated AD1 content
    ad1_creating_app1 = {
        'name': 'Cygwin',
        'version': 'NT-10.0',
        'date': date(2015, 9, 24)
    }
    ad1_creating_app0 = {
        'name': 'AccessData FTK Imager',
        'version': '3.1.2.0',
        'date': date(2015, 3, 6)
    }
    ad1_migration_user = 'aeckhar'  # user who did the migration work
    ad1_migration_event_detail = 'Extraction: program="AccessData FTK Imager"; version="3.1.2.0" Tar repackaging: program="Cygwin"; version="NT-10.0"'
    ad1_migration_event_outcome = 'AD1 downloaded from repository, files extracted, files repackaged as tar file and ingested.'

    def handle(self, *args, **kwargs):
        verbosity = kwargs.get('verbosity', self.v_normal)
        repo = Repository()

        bags = glob.glob('%s/*/bagit.txt' % kwargs['directory'].rstrip('/'))
        if not bags:
            self.stderr.write('No bagit content found to migrate')
            return

        stats = defaultdict(int)

        for bagname in bags:
            bagpath = os.path.dirname(bagname)
            # for now, assuming bagit name is noid portion of object pid
            noid = os.path.basename(bagpath)
            # find the original that this is a migration of
            original = repo.get_object('%s:%s' % (kwargs['pidspace'], noid),
                type=DiskImage)
            # make sure object exists and is a disk image
            if not original.exists:
                self.stderr.write('%s not found in Fedora' % original.pid)
                stats['notfound'] += 1
                continue
            elif not original.has_requisite_content_models:
                self.stderr.write('%s is not a disk image; skipping' % original.pid)
                stats['not_diskimage'] += 1
                continue
            elif original.migrated is not None:
                # also make sure object doesn't already have a migration
                self.stderr.write('%s already has a migration; skipping' % original.pid)
                stats['previously_migrated'] += 1
                continue
            else:
                if verbosity > self.v_normal:
                    self.stdout.write('Migrating %s' % original.pid)

            # create a new "migrated" disk image object from the bag
            migrated = DiskImage.init_from_bagit(bagpath, file_uri=kwargs['file_uris'])
            # associate with original
            migrated.original = original
            # copy over descriptive & rights metadata
            # - collection membership
            migrated.collection = original.collection
            # - mods title, covering dates, abstract
            migrated.mods.content.title = original.mods.content.title
            migrated.mods.content.abstract = original.mods.content.abstract
            migrated.mods.content.coveringdate_start = original.mods.content.coveringdate_start
            migrated.mods.content.coveringdate_end = original.mods.content.coveringdate_end
            # - entire rights datastream
            migrated.rights.content = original.rights.content

            ### Update generated premis to describe migration.
            premis_ds = migrated.provenance.content
            # migrated objects have *two* objectCharacteristics; the one
            # generated by init is closer to what we need for the second,
            # so make some changes there
            premis_ds.object.composition_level = 1
            # these values are the same for all migrated AD1s
            premis_ds.object.create_creating_application()
            premis_ds.object.creating_application.name = self.ad1_creating_app1['name']
            premis_ds.object.creating_application.version = self.ad1_creating_app1['version']
            premis_ds.object.creating_application.date = self.ad1_creating_app1['date']
            # then insert the 0-level object characteristics
            obj_characteristics = PremisObjectCharacteristics(composition_level=0)
            # format name required to be valid, but no relevant format
            obj_characteristics.create_format()
            obj_characteristics.format.name = '-'
            obj_characteristics.create_creating_application()
            obj_characteristics.creating_application.name = self.ad1_creating_app0['name']
            obj_characteristics.creating_application.version = self.ad1_creating_app0['version']
            obj_characteristics.creating_application.date = self.ad1_creating_app0['date']
            # insert *before* the other object characteristics section
            premis_ds.object.characteristics.insert(0, obj_characteristics)
            # copy original environment information from original disk image
            # (using deepcopy to avoid removing content from the original)
            premis_ds.object.original_environment = deepcopy(original.provenance.content.object.original_environment)

            # add relationship to the original object
            rel = PremisRelationship(type='derivation')
            rel.subtype = 'has source'
            rel.related_object_type = 'ark'
            rel.related_object_id = original.mods.content.ark
            # relationship must also reference the migration event on the
            # original, which doesn't exist yet.  Generate a migration event
            # id now to use for both
            migration_event_id = uuid.uuid1()
            rel.related_event_type = 'UUID'
            rel.related_event_id = migration_event_id
            premis_ds.object.relationships.append(rel)

            try:
                migrated.save('Ingest migrated version of %s' % original.pid)
                if verbosity >= self.v_normal:
                    self.stdout.write('Migration of %s ingested as %s' % \
                        (original.pid, migrated.pid))
            except DuplicateContent as err:
                self.stderr.write('Duplicate content detected for %s: %s %s' % \
                    (bagpath, err, ', '.join(err.pids)))
                continue
            # would probably be good to catch other fedora errors

            # reinitialize migrated object, just to avoid any issues
            # with accessing ark uri for use in original object premis
            migrated = repo.get_object(migrated.pid, type=DiskImage)

            # once migrated object has been ingested,
            # update original object with migration information
            # - add rels-ext reference to migrated object
            original.migrated = migrated
            # - update premis with migration event and relationship
            migration_event = PremisEvent()
            migration_event.id_type = 'UUID'
            migration_event.id = migration_event_id
            migration_event.type = 'migration'
            migration_event.date = datetime.now().isoformat()
            migration_event.detail = self.ad1_migration_event_detail
            migration_event.outcome = 'Pass'
            migration_event.outcome_detail = self.ad1_migration_event_outcome
            migration_event.agent_type = 'fedora user'
            migration_event.agent_id = self.ad1_migration_user
            # premis wants both source and outcome objects linked in the event
            link_source = PremisLinkingObject(id_type='ark')
            link_source.id = original.mods.content.ark
            link_source.role = 'source'
            link_outcome = PremisLinkingObject(id_type='ark')
            link_outcome.id = migrated.mods.content.ark
            link_outcome.role = 'outcome'
            migration_event.linked_objects.extend([link_source, link_outcome])
            original.provenance.content.events.append(migration_event)
            # add relation to migrated object in to premis object
            rel = PremisRelationship(type='derivation')
            rel.subtype = 'is source of'
            rel.related_object_type = 'ark'
            rel.related_object_id = migrated.mods.content.ark
            rel.related_event_type = 'UUID'
            rel.related_event_id = migration_event.id
            original.provenance.content.object.relationships.append(rel)

            original.save()
            stats['migrated'] += 1

            if verbosity >= self.v_normal:
                self.stdout.write('Updated original %s with migration event' % \
                        original.pid)

        # summarize what was done
        stats['errors'] = stats['notfound'] + stats['not_diskimage'] + stats['previously_migrated']
        self.stdout.write('Migrated %(migrated)d disk images with %(errors)d errors' % stats)
        if stats['errors']:
            if stats['notfound']:
                self.stdout.write('  %(notfound)d not found' % stats)
            if stats['not_diskimage']:
                self.stdout.write('  %(not_diskimage)d not disk image objects' % stats)
            if stats['previously_migrated']:
                self.stdout.write('  %(previously_migrated)d previously migrated' %
                    stats)
