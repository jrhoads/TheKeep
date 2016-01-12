# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='ResearcherIP',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('name', models.CharField(max_length=255)),
                ('ip_address', models.IPAddressField(verbose_name=b'IP Address')),
            ],
            options={
                'verbose_name': 'Researcher IP',
            },
            bases=(models.Model,),
        ),
    ]