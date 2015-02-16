from collections import defaultdict, namedtuple
from contextlib import contextmanager
import csv
import logging
from optparse import make_option
import os
from sunburnt import sunburnt
import sys

from django.conf import settings
from django.core.management.base import BaseCommand

from eulfedora.util import RequestFailed, ChecksumMismatch

from keep.audio.models import AudioObject, wav_duration
from keep.common.fedora import Repository
from keep.file.utils import md5sum

logger = logging.getLogger(__name__)

AudioFile = namedtuple('AudioFile', 
        ('wav', 'm4a', 'md5', 'jhove'))

class Command(BaseCommand):
    '''Migrate files for metadata-only items generated from the old
    Digital Masters database (using migrate_metadata) into the new
    Repository-based system.'''
    help = __doc__

    args = '<pid pid dm_id other_id pid ...>'
    option_list = BaseCommand.option_list + (
        make_option('--csvoutput', '-c',
            help='''Output CSV data to the specified filename'''),
        make_option('--max', '-m',
            type='int',
            help='''Stop after updating the specified number of items'''),
        make_option('--dry-run', '-n',
            default=False,
            action='store_true',
            help='Report on what would be done, but don\'t actually migrate anything'),
        )

    # text output to put in the CSV file for each file, based on the
    # return value from update_datastream
    file_ingest_status = {
        True: 'OK',
        False: 'FAIL',
        None: 'present'
    }

    def handle(self,  *pids, **options):
        stats = defaultdict(int)
        # limit to max number of items if specified
        max_items = None
        if 'max' in options and options['max']:
            max_items = options['max']
        # verbosity should be set by django BaseCommand standard options
        self.verbosity = int(options['verbosity'])    # 1 = normal, 0 = minimal, 2 = all
        self.v_normal = 1

        if options['dry_run']:
            if self.verbosity >= self.v_normal:
                self.stdout.write('Migration dry run. Audio Objects and corresponding ' +
                         'file paths will be examined, but no files will be ' +
                         'migrated into Fedora. To migrate files, run ' +
                         'without the -n/--dry-run option.\n\n')

        
        self.claimed_files = set()

        # if there are any dm1 ids, convert them to fedora pids
        pids = self.dmids_to_pids(pids)

        with self.open_csv(options) as csvfile:
            if csvfile:
                FIELDS = ('pid', 'dm1_id', 'dm1_other_id',
                          'wav', 'm4a', 'md5', 'jhove',
                          'wav MD5', 'wav ingested', 'm4a ingested', 'jhove ingested')
                csvfile.writerow(FIELDS)

            for obj in self.audio_objects(pids):
                stats['audio'] += 1
                mods = obj.mods.content
                # only objects with a dm1 id will have files that need to be migrated
                old_id = mods.dm1_other_id or mods.dm1_id
                if not old_id:
                    if self.verbosity > self.v_normal:
                        self.stdout.write('%s: no DM1 id. skipping.\n' % (obj.pid,))
                    continue

                stats['dm1'] += 1
                if self.verbosity > self.v_normal:
                    self.stdout.write('Found %s (dm1 id %s) %s\n' % \
                                      (obj.pid, old_id,
                                      mods.title.encode('utf-8')))
                paths = self.look_for_files(obj)
                if not paths:
                    self.stdout.write("Error on %s: couldn't predict path. skipping.\n" % \
                                      (obj.pid,))
                    continue

                if not paths.wav:
                    self.stdout.write("Error: %s=%s missing WAV file\n" % (obj.pid, old_id))
                    stats['no_wav'] += 1


                file_info = []	# info to report in CSV file
                files_updated = 0
                # logic to actually add files to fedora objects
                # - only execute when not in dry-run mode
                if not options['dry_run']:
                    # keep track of any files that are migrated into fedora

                    # if there is a stored MD5 checksum for the WAV file, use that
                    if paths.md5:
                        with open(paths.md5) as md5file:
                            wav_md5 = md5file.read().strip()
                     # otherwise, let update_datastream calculate the MD5
                    else:
                        wav_md5 = None
                    file_info.append(wav_md5)
                    # add the WAV file as contents of the primary audio datastream
                    wav_updated = self.update_datastream(obj.audio, paths.wav, wav_md5)
                    if wav_updated:	# True = successfully ingested/updated
                        files_updated += 1
                    file_info.append(self.file_ingest_status[wav_updated])
                        
                    # Continue even if the WAV fails; it may have
                    # to be handled manually, but having the other
                    # files migrated should still be valuable
                    
                    # for newly ingested objects, audio file duration
                    # is calculated and stored at ingest; go ahead and
                    # do that for migration content, too
                    obj.digitaltech.content.duration = '%d' % round(wav_duration(paths.wav))
                    if obj.digitaltech.isModified():
                        if self.verbosity > self.v_normal:
                            self.stdout.write('Adding WAV file duration to DigitalTech')
                            obj.digitaltech.save('duration calculated from WAV file during migration')


                    # if m4a is present, add it as compressed audio datastream
                    if paths.m4a:
                        # Set the correct mimetype, since migrated content is M4A,
                        # while newly ingested content uses MP3s for access
                        obj.compressed_audio.mimetype = 'audio/mp4'
                        m4a_updated = self.update_datastream(obj.compressed_audio, paths.m4a)
                        if m4a_updated:
                            files_updated += 1
                        file_info.append(self.file_ingest_status[m4a_updated])
                    else:
                        file_info.append('')	# blank to indicate no file

                    # if jhove is present, add it to the object
                    if paths.jhove:
                        jhove_updated = self.update_datastream(obj.jhove, paths.jhove)
                        if jhove_updated:
                            files_updated += 1
                        file_info.append(self.file_ingest_status[jhove_updated])
                    else:
                        file_info.append('')	# blank to indicate no file

                if files_updated or options['dry_run']:
                    stats['updated'] += 1
                    stats['files'] += files_updated

                if csvfile:
                    row_data = [ obj.pid, obj.mods.content.dm1_id,
                                 obj.mods.content.dm1_other_id ] + \
                                 list(paths) + file_info
                    csvfile.writerow(row_data)

                # if a maximum was specified, check if we are at the limit
                # - it's a little bit arbitrary which count we use here; audio items?
                #   dm1 items? going with updated items as it seems the most useful
                if max_items is not None and stats['updated'] > max_items:
                    break

        # if we are not migrating everything (limited either by max or specified pids),
        # skip the unclaimed files check
        if max_items is not None or pids:
            if self.verbosity > self.v_normal:
                self.stdout.write('\nSkipping unclaimed file check because migration was limited\n')
        else:
            # look for any audio files not claimed by a fedora object
            self.check_unclaimed_files()

        if self.verbosity >= self.v_normal:
            self.stdout.write('\nTotal DM1 objects: %(dm1)d (of %(audio)d audio objects)\n' \
                              % stats)
            self.stdout.write('%(updated)d object(s) updated, %(files)d files migrated\n' \
                              % stats)
            self.stdout.write('Missing WAV file: %(no_wav)d\n' % stats)

    @contextmanager
    def open_csv(self, options):
        if options['csvoutput']:
            with open(options['csvoutput'], 'wb') as f:
                csvfile = csv.writer(f)
                yield csvfile
        else:
            yield None

    def audio_objects(self, pids=list()):
        '''Find AudioObjects in the repository for files to be added.
        Takes an optional list of pids.  If specified, returns a
        generator of :class:`~keep.audio.models.AudioObject` instances
        for the specified pids.  Otherwise, returns all Fedora objects
        with the AudioObject content model, as instances of AudioObject.
        '''
        repo = Repository()
        if pids:
            return (repo.get_object(pid, type=AudioObject) for pid in pids)
        cmodel = AudioObject.AUDIO_CONTENT_MODEL
        return repo.get_objects_with_cmodel(cmodel, type=AudioObject)

    def look_for_files(self, obj):
        access_path = obj.old_dm_media_path()
        if not access_path:
            return
        basename, ext = os.path.splitext(access_path)

        return AudioFile(*[self.dm_path(basename, ext)
                           for ext in ('wav', 'm4a', 'wav.md5', 'wav.jhove')])

    def dm_path(self, basename, ext):
        for try_ext in self.ext_cap_variants(ext):
            rel_path = '%s.%s' % (basename, try_ext)
            abs_path = os.path.join(settings.MIGRATION_AUDIO_ROOT, rel_path)
            if os.path.exists(abs_path):
                if self.verbosity > self.v_normal:
                    self.stdout.write('  found path: %s\n' % abs_path)
                # keep track of files that belong to an object
                self.claimed_files.add(abs_path)
                return abs_path

        # otherwise, no match
        if self.verbosity > self.v_normal:
            self.stdout.write('  missing path: %s\n' % (abs_path,))

    def ext_cap_variants(self, ext):
        # Extensions are sometimes capitalized and sometimes not. For
        # multi-extension files, sometimes one will be capitalized and
        # another not. Recursively generate all possible capitalization
        # variants.
        first, dot, rest = ext.partition('.')
        if rest:
            variants = self.ext_cap_variants(rest)
            return ([ '%s.%s' % (first.lower(), v) for v in variants ] +
                    [ '%s.%s' % (first.upper(), v) for v in variants ])
        else:
            return [ first.lower(), first.upper() ]


    def check_unclaimed_files(self):
        '''Scan for any audio files under the configured
        MIGRATION_AUDIO_ROOT directory that have not been claimed by
        an AudioObject in Fedora.  This function will compare any file
        in a directory named "audio" at any depth under the migration
        root directory, and warn about any files that have not been
        already identified as corresponding to an AudioObject.  
        '''
        # should only be run after the main script logic has looked
        # for files and populated self.claimed_files
        if self.verbosity >= self.v_normal:
            self.stdout.write('Checking for unclaimed audio files\n')
        # traverse the configured migration directory
        for root, dirnames, filenames in os.walk(settings.MIGRATION_AUDIO_ROOT):
            # if we are in an audio directory, check the files
            base_path, current_dir = os.path.split(root)
            if current_dir == 'audio':
                for f in sorted(filenames):
                    full_path = os.path.join(root, f)
                    # warn about any files not in the claimed set
                    if full_path not in self.claimed_files:
                        self.stdout.write('Warning: %s is unclaimed\n' % full_path)

    def dmids_to_pids(self, ids):
        '''Takes a list of ids with a mix of fedora object pids and
        dm1 ids or dm1 other ids, and looks up any dm1 ids in Solr to
        find the corresponding pid.  Returns a list of fedora object
        pids.'''

        pids = set()
        solr = sunburnt.SolrInterface(settings.SOLR_SERVER_URL)
        for id in ids:
            # purely numeric ids are expected to be dm1 id or other id
            if id.isdigit():
                # look up the dm1 id in solr and return just the object pid
                result = solr.query(dm1_id=id).field_limit('pid').execute()
                if result:
                    if len(result) > 1:
                        self.stdout.write('Found too many pids for dm1 id %s: %s\n' % \
                                    (id, ', '.join(r['pid'] for r in result)))
                    else:
                        pids.add(result[0]['pid'])
                else:
                    self.stdout.write('Could not find a pid for dm1 id %s\n' % id)
            else:
                pids.add(id)
        return pids


    def update_datastream(self, ds, filepath, checksum=None):
        '''Update the contents of a single datastream in Fedora.  If
        the datastream already exists and the checksum matches the one
        passed in, no updates will be made.

        :param ds: :class:`eulfedora.models.DatastreamObject` the
            datastream to be updated
        :param filepath: full path to the file whose contents should
            be stored in the datastream
        :param checksum: the MD5 checksum for the file contents; if
            not specified, an MD5 checksum will be calculated for the
            file passed in

        :returns: True if the datastream was saved; None if no action
            was needed (datastream was already present with the
            expected checksum), or False if the update failed
        '''
        if checksum is None:
            if self.verbosity > self.v_normal:
                self.stdout.write('Calculating checksum for %s\n' % filepath)
            checksum = md5sum(filepath)

        # - if the content already exists with the correct checksum
        # (e.g., from a previous file migration run), skip it
        if ds.exists and ds.checksum == checksum:
            if self.verbosity > self.v_normal:
                self.stdout.write('%s already has %s datastream with the expected checksum; skipping\n' \
                                  % (ds.obj.pid, ds.id))
            return None
        
        # datastream does not yet exist or does not have the expected content
        # migrate the file into the repository
        else:
            with open(filepath) as filecontent:
                ds.content = filecontent
                ds.checksum_type = 'MD5'  
                ds.checksum = checksum
                try:
                    # save just this datastream
                    success = ds.save('Migrated from legacy Digital Masters file %s\n' % \
                             filepath)
                    if success:
                        if self.verbosity > self.v_normal:
                            self.stdout.write('Successfully updated %s/%s\n' \
                                          % (ds.obj.pid, ds.id))
                        return True
                    else:
                        if self.verbosity >= self.v_normal:
                            self.stdout.write('Error updating %s/%s\n' \
                                              % (ds.obj.pid, ds.id))
                except RequestFailed as rf:
                    self.stdout.write('Error saving %s/%s: %s\n' % \
                                      (ds.obj.pid, ds.id, rf))

        # FIXME: do we need to handle file read permission errors? 

        # successful update should already have returned - indicates some kind of error
        return False



                    
