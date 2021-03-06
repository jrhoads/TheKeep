from celery import shared_task, states
from celery.exceptions import Ignore
from celery.utils.log import get_task_logger
from datetime import date, datetime
from django.conf import settings
from django.template.defaultfilters import filesizeformat
from eulfedora.models import FileDatastreamObject
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib
import uuid

from keep.common.fedora import Repository, DuplicateContent
from keep.common.models import PremisRelationship, PremisEvent, \
    PremisLinkingObject
from keep.file.models import DiskImage
from keep.file.utils import md5sum


logger = get_task_logger(__name__)


@shared_task(bind=True)
def migrate_aff_diskimage(self, pid):
    creating_application = 'AccessData FTK Imager'
    application_version = 'v3.1.1 CLI'
    migration_event_detail = 'program="%s"; version="%s"' % \
        (creating_application, application_version)
    migration_event_outcome = 'AFF reformatted as E01 using command line ' + \
        'FTK program with settings: --e01 --compress 0 --frag 100T --quiet'

    # use the configured ingesting staging area as the base tmp dir
    # create
    # for all temporary files
    staging_dir = getattr(settings, 'LARGE_FILE_STAGING_DIR', None)
    # create a tempdir within the large file staging area
    tmpdir = tempfile.mkdtemp(suffix='-aff-migration', dir=staging_dir)
    logger.debug('Using tmpdir %s', tmpdir)

    # Retrieve the object to be migrated
    repo = Repository()
    original = repo.get_object(pid, type=DiskImage)

    # check object before migrating
    # - exists in fedora
    if not original.exists:
        # raise Exception
        raise Exception('%s not found in Fedora' % original.pid)
    # - is a disk image
    if not original.has_requisite_content_models:
        raise Exception('%s is not a DiskImage object' % original.pid)
    # - is an AFF disk image
    if original.provenance.content.object.format.name != 'AFF':
        raise Exception('%s DiskImage format is not AFF' % original.pid)
    # - has not already been migrated
    if original.migrated is not None:
        raise Exception('%s has already been migrated' % original.pid)

    # download the aff disk image to a tempfile
    aff_file = tempfile.NamedTemporaryFile(suffix='.aff',
        prefix='keep-%s_' % original.noid, dir=tmpdir, delete=False)
    logger.debug('Saving AFF as %s for conversion (datastream size: %s)' \
        % (aff_file.name, filesizeformat(original.content.size)))
    try:
        for chunk in original.content.get_chunked_content():
            aff_file.write(chunk)
    except Exception as err:
        raise Exception('Error downloading %s AFF for conversion' % original.pid)

    # close the file handle in case of weird interactions with ftkimager
    aff_file.close()
    aff_size = os.path.getsize(aff_file.name)
    logger.debug('Downloaded %s' % filesizeformat(aff_size))

    # run ftkimager to generate the E01 version
    logger.debug('Running ftkimager to generate E01')
    e01_file = tempfile.NamedTemporaryFile(suffix='.E01',
        prefix='keep-%s_' % original.noid, dir=tmpdir, delete=False)
    # close the file handle in case of weird interactions with ftkimager
    e01_file.close()
    # file handle to capture console output from ftkimager
    ftk_output = tempfile.NamedTemporaryFile(suffix='.txt',
        prefix='keep-%s-ftkimager_' % original.noid, dir=tmpdir)
    logger.debug('E01 temp file is %s' % e01_file.name)
    logger.debug('ftkimager output temp file is %s' % ftk_output.name)
    # ftkimager adds .E01 to the specified filename, so pass in filename without
    e01_file_basename, ext = os.path.splitext(e01_file.name)

    convert_command = ['ftkimager', aff_file.name, e01_file_basename,
        '--e01', '--compress', '0', '--frag', '100T', '--quiet']
    # quiet simply suppresses progress output, which is not meaningful
    # in a captured text file
    logger.debug('conversion command is %s' % ' '.join(convert_command))
    return_val = subprocess.call(convert_command, stdout=ftk_output,
        stderr=subprocess.STDOUT)
    logger.debug('ftkimager return value is %s' % return_val)
    ftk_detail_output = '%s.txt' % e01_file.name

    e01_size = os.path.getsize(e01_file.name)
    if e01_size == 0:
        raise Exception('Generated E01 file is 0 size')

    logger.info('Generated E01 (%s) from %s AFF (%s)' % \
        (filesizeformat(e01_size), original.pid, filesizeformat(aff_size)))

    # use ftkimager to verify aff and e01 and compare checksums
    aff_checksums = ftkimager_verify(aff_file.name)
    if not aff_checksums:
        raise Exception('Error running ftkimager verify on AFF for %s' % original.pid)
    e01_checksums = ftkimager_verify(e01_file.name)
    if not e01_checksums:
        raise Exception('Error running ftkimager verify on E01 for %s' % original.pid)

    logger.debug('AFF verify checksums: %s' % \
        ', '.join('%s: %s' % (k, v) for k, v in aff_checksums.iteritems()))
    logger.debug('E01 verify checksums: %s' % \
        ', '.join('%s: %s' % (k, v) for k, v in e01_checksums.iteritems()))
    if aff_checksums != e01_checksums:
        raise Exception('AFF and E01 ftkimager verify checksums do not match')

    # create a new diskimage object from the file
    # - calculate file uri for content location
    e01_file_uri = fedora_file_uri(e01_file.name)
    logger.debug('E01 fedora file URI is %s', e01_file_uri)

    # change permissions on tmpdir + files to ensure fedora can access them
    os.chmod(tmpdir, 0775)
    os.chmod(e01_file.name, 0666)
    os.chmod(ftk_output.name, 0666)
    os.chmod(ftk_detail_output, 0666)

    migrated = DiskImage.init_from_file(e01_file.name,
        initial_label=original.label, content_location=e01_file_uri)

    # add ftkimager text output & details as supplemental files
    # - console output captured from subprocess call
    dsobj = migrated.getDatastreamObject('supplement0', dsobj_type=FileDatastreamObject)
    dsobj.label = 'ftkimager_output.txt'
    dsobj.mimetype = 'text/plain'
    dsobj.checksum = md5sum(ftk_output.name)
    logger.debug('Adding ftkimager console output as supplemental dastream %s label=%s mimetype=%s checksum=%s' % \
                (dsobj.id, dsobj.label, dsobj.mimetype, dsobj.checksum))
    dsobj.content = open(ftk_output.name).read()
    # - text file generated by ftkimager alongside the E01
    dsobj2 = migrated.getDatastreamObject('supplement1', dsobj_type=FileDatastreamObject)
    dsobj2.label = 'ftkimager_summary.txt'
    dsobj2.mimetype = 'text/plain'
    dsobj2.checksum = md5sum(ftk_detail_output)
    logger.debug('Adding ftkimager summary as supplemental dastream %s label=%s mimetype=%s checksum=%s' % \
                (dsobj2.id, dsobj2.label, dsobj2.mimetype, dsobj2.checksum))
    dsobj2.content = open(ftk_detail_output).read()

    # set metadata based on original disk image
    # - associate with original
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
    premis_ds.object.composition_level = 0
    # these values are the same for all migrated AFFs
    premis_ds.object.create_creating_application()
    premis_ds.object.creating_application.name = creating_application
    premis_ds.object.creating_application.version = application_version
    premis_ds.object.creating_application.date = date.today()

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

    ## NOTE: Due to a Fedora bug with checksums and file uri ingest,
    ## content datastream checksum must be cleared out before ingest
    ## and manually checked after.

    # store datastream checksum that would be sent to fedora
    e01_checksum = migrated.content.checksum
    # clear it out so Fedora can ingest without erroring
    migrated.content.checksum = None

    # ingest
    try:
        migrated.save('Ingest migrated version of %s' % original.pid)
        logger.debug('Migrated object ingested as %s' % migrated.pid)
    except DuplicateContent as err:
        raise Exception('Duplicate content detected for %s: %s %s',
            original.pid, err, ', '.join(err.pids))
    # would probably be good to catch other fedora errors

    # remove temporary files
    for tmpfilename in [aff_file.name, e01_file.name, ftk_output.name,
                        ftk_detail_output]:
        os.remove(tmpfilename)

    # reinitialize migrated object, just to avoid any issues
    # with accessing ark uri for use in original object premis
    migrated = repo.get_object(migrated.pid, type=DiskImage)
    # verify checksum
    if migrated.content.checksum != e01_checksum:
        raise Exception('Checksum mismatch detected on E01 for %s', migrated.pid)

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
    migration_event.detail = migration_event_detail
    migration_event.outcome = 'Pass'
    migration_event.outcome_detail = migration_event_outcome
    migration_event.agent_type = 'fedora user'
    migration_event.agent_id = repo.username
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
    logger.debug('Original disk image updated with migration data')

    # remove aff migration temp dir and any remaining contents
    try:
        shutil.rmtree(tmpdir)
    except OSError:
        # tempdir removal could fail due to nfs files
        # wait a few seconds and try again
        time.sleep(3)
        try:
            shutil.rmtree(tmpdir)
        except OSError as os_err:
            logger.warning('Failed to remove tmpdir %s : %s',
                tmpdir, os_err)

    logger.info('Migrated %s AFF to %s E01' % (original.pid, migrated.pid))
    return 'Migrated %s to %s' % (original.pid, migrated.pid)

#: Regular Expression to find a computed MD5 or SHA1 hash in
#: ftkimager verify output
FTKIMAGER_HASH_RE = re.compile(r'\[(MD5|SHA1)\]\s+Computed hash: ([0-9A-Fa-f]+)',
    flags=re.MULTILINE)
# ftkimager verify output includes checksums in this format:
# [MD5]
#  Computed hash: 1a66df5b197ecbfd29338cc53d9db7c3
# [SHA1]
#  Computed hash: ccfdacc203ada4b0741a4784d15004bfbc2e520d


def ftkimager_verify(filename):
    '''Use ftkimager to verify a disk image file.

    :param filename: path to file to be verified
    :returns: dict of checksums (MD5 and SHA1) from verification output
    '''
    verify_command = ['ftkimager', '--verify', filename]
    try:
        output = subprocess.check_output(verify_command,
            stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as err:
        logger.error('ftkimager verification failed on %s: %s' % \
            (filename, err))
        return

    # regular expression search returns a list of tuples with
    # checksum type and value; convert into a dict keyed on checksum type
    return dict(FTKIMAGER_HASH_RE.findall(output))


def fedora_file_uri(filename):
    filename = 'file://%s' % urllib.quote(filename)
    # if Fedora base path is different from locally mounted staging directory,
    # convert from local path to fedora server path
    if getattr(settings, 'LARGE_FILE_STAGING_FEDORA_DIR', None) is not None:
        filename = filename.replace(settings.LARGE_FILE_STAGING_DIR,
            settings.LARGE_FILE_STAGING_FEDORA_DIR)
    return filename
