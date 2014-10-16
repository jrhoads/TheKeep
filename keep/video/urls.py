from django.conf.urls import *
from keep.video import views

urlpatterns = patterns('',
    url(r'^(?P<pid>[^/]+)/$', views.view, name='view'),
    url(r'^(?P<pid>[^/]+)/history/$', views.history, name='history'),
    url(r'^ds/(?P<pid>[^/]+)/(?P<dsid>[a-zA-Z-0-9]+)/$',
        views.view_datastream, name='raw-ds'),
    url(r'^(?P<pid>[^/]+)/AUDIT/$', views.view_audit_trail, name='audit-trail')
)