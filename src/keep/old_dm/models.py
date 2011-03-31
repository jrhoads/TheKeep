# This is an auto-generated Django model module.
# You'll have to do the following manually to clean this up:
#     * Rearrange models' order
#     * Make sure each model has one field with primary_key=True
# Feel free to rename the models, but don't rename db_table values or field names.
#
# Also note: You'll have to insert the output of 'django-admin.py sqlcustom [appname]'
# into your database.

from django.db import models

class ResourceType(models.Model):
    id = models.IntegerField(primary_key=True)
    type = models.CharField(max_length=100, db_column='resource_type')
    class Meta:
        db_table = u'resource_types'
        managed = False

    def __unicode__(self):
        return self.type

class DescriptionData(models.Model):
    id = models.IntegerField(primary_key=True)
    #main_entry = models.CharField()
    #title_statement = models.CharField()

    class Meta:
        db_table = u'description_datas'
        managed = False

class StaffName(models.Model):
    id = models.IntegerField(primary_key=True)
    name = models.CharField(max_length=100)
    class Meta:
        db_table = u'staff_names'
        managed = False

    def __unicode__(self):
        return self.name


class Authority(models.Model):
    id = models.IntegerField(primary_key=True)
    authority = models.CharField(max_length=255)
    class Meta:
        db_table = u'authorities'
        managed = False

    def __unicode__(self):
        return self.authority

class Genre(models.Model):
    id = models.IntegerField(primary_key=True)
    genre = models.CharField(max_length=255)
    authority = models.ForeignKey(Authority)
    fieldnames = models.IntegerField()
    class Meta:
        db_table = u'genres'
        managed = False

    def __unicode__(self):
        return '%s [authority = %s, field = %d]' % (self.genre, self.authority.authority, self.fieldnames)

class AudioItemManager(models.Manager):
    # custom manager to find audio items only, using resource type
    def get_query_set(self):
        # filter on resource type: starting with sound recording, will also match musical & nonmusical variant types
        return super(AudioItemManager, self).get_query_set().filter(resource_type__type__startswith='sound recording')

class Content(models.Model):   # individual item
    id = models.IntegerField(primary_key=True)
    record_id_type = models.CharField(max_length=50)
    other_id = models.CharField(max_length=255)
    created_at = models.DateTimeField()
    modified_at = models.DateTimeField()
    collection_number = models.IntegerField()
    title = models.CharField(max_length=255)
    subtitle = models.CharField(max_length=255)
    resource_type = models.ForeignKey(ResourceType)
    location_id = models.IntegerField()
    abstract = models.TextField()
    toc = models.TextField()
    note = models.TextField(db_column='content_notes')
    completed_by = models.IntegerField()
    completed_date = models.DateTimeField()
    data_entered_by = models.ForeignKey(StaffName, db_column='data_entered_by',
                                        related_name='entered_data', null=True)
    data_entered_date = models.DateTimeField()
    authority_work_by = models.ForeignKey(StaffName, db_column='authority_work_by',
                                          related_name='authority_work', null=True)
    authority_work_date = models.DateTimeField()
    initial_qc_by = models.ForeignKey(StaffName, db_column='initial_qc_by',
                                      related_name='quality_control', null=True)
    initial_qc_date = models.DateTimeField()

    # source_sounds (one to many; most items seem to have 0 or 1)
    genres = models.ManyToManyField(Genre)

    # default manager & custom audio-only manager
    objects = models.Manager()
    audio_objects = AudioItemManager()

    class Meta:
        db_table = u'contents'
        managed = False

    def __unicode__(self):
        return '%s' % self.id

    def descriptive_metadata(self):
        print '--- Descriptive Metadata --'
        # TODO: collection
        print 'Identifier: %s' % self.id
        print 'Other ID: %s' % self.other_id
        # source_sound could be multiple; which one do we use?
        if self.source_sounds.count() > 1:
            print '# source sounds = ', self.source_sounds.count()
        for source_sound in self.source_sounds.all():
            print 'Item Date Created: %s' % source_sound.source_date
            print 'Item Date Issued: %s' % source_sound.publication_date
        print 'Item Note: %s' % self.note
        print 'Item Title: %s' % self.title
        print 'Item Type of Resource: %s' % self.resource_type.type
        if self.data_entered_by:
            print 'Item recordOrigin: %s' % self.data_entered_by.name
        for genre in self.genres.all():
            print 'Item Genre: %s' % unicode(genre)
        

    def source_tech_metadata(self):
        print '--- Source Technical Metadata ---'

        # XXX since source_sound is repeatable, check all fields'
        # repeatability in tech metadata spec

        for source_sound in self.source_sounds.all():
            if source_sound.source_note:
                print 'Note - General: %s' % source_sound.source_note
            if source_sound.sound_field:
                print 'Note - General: %s' % source_sound.sound_field
            if source_sound.related_item:
                print 'Note - Related Files: %s' % source_sound.related_item
            if source_sound.conservation_history:
                print 'Note - Conservation History: %s' % source_sound.conservation_history
            if source_sound.speed:
                print 'Speed: %s (unit: %s)' % (source_sound.speed.speed, source_sound.speed.unit)
            if source_sound.item_location:
                print 'Item Sub-Location: %s' % source_sound.item_location
            if source_sound.form:
                print 'Item Form: %s' % source_sound.form.short_form
            if source_sound.sound_field:
                print 'Sound Characteristics: %s' % source_sound.sound_field
            if source_sound.stock:
                print 'Tape - Brand/Stock: %s' % source_sound.stock
            if source_sound.housing:
                # FIXME: cleanup "Moving Image/Sound:" in front of desc?
                print 'Tape - Housing: %s' % source_sound.housing.description
            if source_sound.reel_size:
                # FIXME: cleanup '"' at end of reel_size?
                print 'Tape - Reel Size: %s' % source_sound.reel_size
        

class AccessRights(models.Model):
    id = models.IntegerField(primary_key=True)
    restriction_id = models.IntegerField()
    restriction_other = models.CharField(max_length=255)
    content_id = models.IntegerField()
    name_id = models.IntegerField()
    copyright_date = models.CharField(max_length=50)
    class Meta:
        db_table = u'access_rights'
        managed = False

class CodecCreatorSounds(models.Model):
    id = models.IntegerField(primary_key=True)
    hardware = models.CharField(max_length=100)
    software = models.CharField(max_length=100)
    software_version = models.CharField(max_length=100)
    class Meta:
        db_table = u'codec_creator_sounds'
        managed = False

class ColorSpaces(models.Model):
    id = models.IntegerField(primary_key=True)
    color_space = models.CharField(max_length=50)
    class Meta:
        db_table = u'color_spaces'
        managed = False

class Conditions(models.Model):
    id = models.IntegerField(primary_key=True)
    condition = models.CharField(unique=True, max_length=150)
    class Meta:
        db_table = u'conditions'
        managed = False

class ContentsConditions(models.Model):
    content_id = models.IntegerField()
    condition_id = models.IntegerField()
    class Meta:
        db_table = u'contents_conditions'
        managed = False

class ContentsGenres(models.Model):
    id = models.IntegerField(primary_key=True)
    content_id = models.IntegerField()
    genre_id = models.IntegerField()
    class Meta:
        db_table = u'contents_genres'
        managed = False

class ContentsLanguages(models.Model):
    content_id = models.IntegerField()
    language_id = models.IntegerField()
    id = models.IntegerField(primary_key=True)
    class Meta:
        db_table = u'contents_languages'
        managed = False

class Locations(models.Model):
    id = models.IntegerField(primary_key=True)
    name = models.CharField(max_length=100)
    address = models.CharField(max_length=255)
    phone = models.CharField(max_length=50)
    fax = models.CharField(max_length=50)
    email = models.CharField(max_length=50)
    url = models.TextField()
    city = models.CharField(max_length=100)
    state = models.TextField() # This field type is a guess.
    zip = models.TextField() # This field type is a guess.
    class Meta:
        db_table = u'locations'
        managed = False

class Form(models.Model):
    id = models.IntegerField(primary_key=True)
    form = models.CharField(max_length=150)
    support_material = models.CharField(max_length=50)
    dates = models.CharField(max_length=50)
    identifying_features = models.TextField()
    source = models.CharField(max_length=255)
    class Meta:
        db_table = u'forms'
        managed = False

    def __unicode__(self):
        return '%s' % self.id

    @property
    def short_form(self):
        form = self.form
        if form.startswith('Sound - '):
            form = form[len('Sound - '):]
        return form

class Languages(models.Model):
    id = models.IntegerField(primary_key=True)
    language = models.CharField(max_length=255)
    code = models.CharField(max_length=255)
    class Meta:
        db_table = u'languages'
        managed = False

class Roles(models.Model):
    id = models.IntegerField(primary_key=True)
    title = models.CharField(max_length=255)
    code = models.CharField(max_length=255)
    class Meta:
        db_table = u'roles'
        managed = False

class Speed(models.Model):
    id = models.IntegerField(primary_key=True)
    speed = models.CharField(max_length=255)
    speed_alt = models.CharField(max_length=255)
    format_type = models.CharField(max_length=255)
    class Meta:
        db_table = u'speeds'
        managed = False

    def __unicode__(self):
        return '%s' % self.id

    @property
    def unit(self):
        if self.speed_alt == 'Multiple':
            return 'multiple'
        elif self.speed_alt == 'Other':
            return 'other'
        elif self.speed_alt.endswith('rpm'):
            return 'rpm'
        elif self.speed_alt.endswith('Kilohertz'):
            return 'Kilohertz'
        elif 'ips' in self.speed_alt:
            return 'inches/sec'


class SrcMovingImages(models.Model):
    id = models.IntegerField(primary_key=True)
    form_id = models.IntegerField()
    disposition = models.CharField(max_length=50)
    generation = models.CharField(max_length=50)
    length = models.IntegerField()
    source_note = models.TextField()
    sound_field = models.CharField(max_length=50)
    stock = models.CharField(max_length=255)
    related_item = models.TextField()
    item_location = models.CharField(max_length=255)
    duration = models.DateTimeField()
    content_id = models.IntegerField()
    housing_id = models.IntegerField()
    color = models.CharField(max_length=50)
    polarity = models.CharField(max_length=50)
    base = models.CharField(max_length=50)
    viewable = models.BooleanField()
    dirty = models.BooleanField()
    scratched = models.BooleanField()
    warped = models.BooleanField()
    sticky = models.BooleanField()
    faded = models.BooleanField()
    vinegar_syndrome = models.BooleanField()
    ad_strip = models.CharField(max_length=50)
    ad_strip_date = models.DateTimeField()
    ad_strip_replace_date = models.DateTimeField()
    conservation_history = models.TextField()
    source_date = models.CharField(max_length=50)
    publication_date = models.CharField(max_length=50)
    class Meta:
        db_table = u'src_moving_images'
        managed = False

class Subjects(models.Model):
    subject = models.CharField(max_length=255)
    id = models.IntegerField(primary_key=True)
    authority_id = models.IntegerField()
    fieldnames = models.IntegerField()
    class Meta:
        db_table = u'subjects'
        managed = False

class ContentsNames(models.Model):
    content_id = models.IntegerField()
    name_id = models.IntegerField()
    role_id = models.IntegerField()
    id = models.IntegerField(primary_key=True)
    class Meta:
        db_table = u'contents_names'
        managed = False

class DigitalProvenances(models.Model):
    id = models.IntegerField(primary_key=True)
    date = models.DateTimeField()
    staff_name_id = models.IntegerField()
    action = models.CharField(max_length=255)
    class Meta:
        db_table = u'digital_provenances'
        managed = False

class EuarchivesContentsSeries(models.Model):
    content_id = models.IntegerField(unique=True)
    series = models.IntegerField()
    class Meta:
        db_table = u'euarchives_contents_series'
        managed = False

class FeedCollections(models.Model):
    mss_number = models.IntegerField(unique=True)
    class Meta:
        db_table = u'feed_collections'
        managed = False



class Housing(models.Model):
    id = models.IntegerField(primary_key=True)
    description = models.CharField(max_length=50)
    class Meta:
        db_table = u'housings'
        managed = False

    def __unicode__(self):
        return '%s' % self.id

class Names(models.Model):
    id = models.IntegerField(primary_key=True)
    name = models.CharField(unique=True, max_length=255)
    authority_id = models.IntegerField()
    name_type = models.CharField(max_length=50)
    class Meta:
        db_table = u'names'
        managed = False



class Restrictions(models.Model):
    id = models.IntegerField(primary_key=True)
    description = models.CharField(max_length=255)
    class Meta:
        db_table = u'restrictions'
        managed = False

class ScannerCameras(models.Model):
    id = models.IntegerField(primary_key=True)
    model_name = models.CharField(max_length=100)
    model_number = models.CharField(max_length=100)
    manufacturer = models.CharField(max_length=100)
    software = models.CharField(max_length=100)
    class Meta:
        db_table = u'scanner_cameras'
        managed = False

class SrcStillImages(models.Model):
    id = models.IntegerField(primary_key=True)
    form_id = models.IntegerField()
    dimension_height = models.FloatField()
    dimension_height_unit = models.CharField(max_length=50)
    dimension_width = models.FloatField()
    dimension_width_unit = models.CharField(max_length=50)
    dimension_note = models.CharField(max_length=255)
    disposition = models.CharField(max_length=50)
    generation = models.CharField(max_length=50)
    source_note = models.TextField()
    related_item = models.TextField()
    item_location = models.CharField(max_length=255)
    content_id = models.IntegerField()
    housing_id = models.IntegerField()
    conservation_history = models.TextField()
    source_date = models.CharField(max_length=50)
    publication_date = models.CharField(max_length=50)
    class Meta:
        db_table = u'src_still_images'
        managed = False

class TargetUrls(models.Model):
    id = models.IntegerField(primary_key=True)
    content_id = models.IntegerField()
    url = models.CharField(max_length=2000)
    class Meta:
        db_table = u'target_urls'
        managed = False

class Targets(models.Model):
    id = models.IntegerField(primary_key=True)
    name = models.CharField(max_length=255)
    pub = models.CharField(max_length=255)
    external_location = models.TextField()
    class Meta:
        db_table = u'targets'
        managed = False

class TechImages(models.Model):
    id = models.IntegerField(primary_key=True)
    content_id = models.IntegerField()
    format_name_version = models.CharField(max_length=50)
    byte_order = models.CharField(max_length=50)
    compression_scheme = models.CharField(max_length=100)
    color_space_id = models.IntegerField()
    icc_profile = models.CharField(max_length=150)
    y_cb_cr_subsample = models.CharField(max_length=100)
    y_cb_cr_positioning = models.IntegerField()
    y_cb_cr_coefficients = models.CharField(max_length=100)
    ref_bw = models.CharField(max_length=100)
    jpeg2000_profile = models.CharField(max_length=50)
    jpeg2000_class = models.CharField(max_length=50)
    jpeg2000_layers = models.CharField(max_length=50)
    jpeg2000_level = models.CharField(max_length=50)
    mr_sid = models.BooleanField()
    mr_sid_zoom_levels = models.IntegerField()
    file_size = models.IntegerField()
    scanner_camera_id = models.IntegerField()
    methodology = models.CharField(max_length=50)
    image_width = models.FloatField()
    image_length = models.FloatField()
    ppixel_res = models.IntegerField(db_column='pPixel_res') # Field name made lowercase.
    bits_per_sample = models.CharField(max_length=50)
    bits_per_sample_unit = models.CharField(max_length=50)
    samples_per_pixel = models.CharField(max_length=50)
    extra_samples = models.IntegerField()
    target_id = models.IntegerField()
    image_processing = models.CharField(max_length=255)
    gamma = models.CharField(max_length=50)
    scale = models.IntegerField()
    image_note = models.TextField()
    date_captured = models.DateTimeField()
    djvu = models.BooleanField()
    djvu_format = models.CharField(max_length=50)
    deriv_filename = models.CharField(max_length=255)
    file_location = models.CharField(max_length=50)
    digital_provence_id = models.IntegerField()
    url = models.CharField(max_length=1024)
    src_still_image_id = models.IntegerField()
    class Meta:
        db_table = u'tech_images'
        managed = False

class TechMovingImages(models.Model):
    id = models.IntegerField(primary_key=True)
    date_captured = models.DateTimeField()
    format_name = models.CharField(max_length=50)
    resolution = models.IntegerField()
    bits_per_sample = models.IntegerField()
    sampling = models.CharField(max_length=50)
    aspect_ratio = models.IntegerField()
    calibration_ext_int = models.CharField(max_length=50)
    calibrationlocation = models.TextField(db_column='CalibrationLocation') # Field name made lowercase.
    calibration_type = models.CharField(max_length=255)
    data_rate = models.CharField(max_length=50)
    data_rate_mode = models.CharField(max_length=50)
    duration = models.CharField(max_length=50)
    frame_rate = models.IntegerField()
    note = models.TextField()
    pixels_horizontial = models.IntegerField()
    pixels_vertical = models.IntegerField()
    scan = models.CharField(max_length=50)
    sound = models.BooleanField()
    file_location = models.CharField(max_length=50)
    content_id = models.IntegerField()
    class Meta:
        db_table = u'tech_moving_images'
        managed = False

class TechSounds(models.Model):
    id = models.IntegerField(primary_key=True)
    content_id = models.IntegerField()
    format_name = models.CharField(max_length=50)
    byte_order = models.CharField(max_length=50)
    compression_scheme = models.CharField(max_length=100)
    file_size = models.IntegerField()
    codec_creator = models.IntegerField()
    codec_quality = models.CharField(max_length=50)
    methodology = models.CharField(max_length=50)
    bits_per_sample = models.CharField(max_length=50)
    sampling_frequency = models.CharField(max_length=50)
    sound_note = models.TextField()
    duration = models.CharField(max_length=50)
    date_captured = models.DateTimeField()
    file_location = models.CharField(max_length=50)
    sound_clip = models.TextField()
    digital_provenance_id = models.IntegerField()
    src_sound_id = models.IntegerField()
    class Meta:
        db_table = u'tech_sounds'
        managed = False

class TmpExport(models.Model):
    image = models.IntegerField(db_column='Image') # Field name made lowercase.
    title = models.CharField(max_length=255)
    abstract = models.TextField()
    subject = models.CharField(max_length=255)
    fieldnames = models.IntegerField()
    sa_authority = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    na_authority = models.CharField(max_length=255)
    genre = models.CharField(max_length=255)
    ga_authority = models.CharField(max_length=255)
    class Meta:
        db_table = u'tmp_export'
        managed = False

class ContentsSubjects(models.Model):
    id = models.IntegerField(primary_key=True)
    content_id = models.IntegerField()
    subject_id = models.IntegerField()
    class Meta:
        db_table = u'contents_subjects'
        managed = False

class SourceSound(models.Model):
    id = models.IntegerField(primary_key=True)
    reel_size = models.CharField(max_length=50)
    dimension_note = models.CharField(max_length=255)
    disposition = models.CharField(max_length=50)
    gauge = models.CharField(max_length=50)
    generation = models.CharField(max_length=50)
    length = models.CharField(max_length=50)
    source_note = models.TextField()
    sound_field = models.CharField(max_length=50)
    stock = models.CharField(max_length=255)
    tape_thick = models.CharField(max_length=50)
    track_format = models.CharField(max_length=50)
    related_item = models.TextField()
    item_location = models.CharField(max_length=255)
    content = models.ForeignKey(Content, related_name='source_sounds')# db_column='content_id',
    # related_name='source_sounds')
    conservation_history = models.TextField()
    source_date = models.CharField(max_length=50)
    publication_date = models.CharField(max_length=50)
    transfer_engineer_staff_id = models.IntegerField()

    # XXX clean up code for these 0-as-null fields:

    # speed_id == 0 means no speed.
    speed_id = models.IntegerField()
    @property
    def speed(self):
        if self.speed_id:
            return Speed.objects.get(pk=self.speed_id)

    # form_id == 0 means no form.
    form_id = models.IntegerField()
    @property
    def form(self):
        if self.form_id:
            return Form.objects.get(pk=self.form_id)

    # housing_id == 0 means no form.
    housing_id = models.IntegerField()
    @property
    def housing(self):
        if self.housing_id:
            return Housing.objects.get(pk=self.housing_id)

    class Meta:
        db_table = u'src_sounds'
        managed = False

