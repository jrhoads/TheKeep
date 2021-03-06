from django import template
from django.template.defaultfilters import stringfilter
from keep.common.models import rights_access_terms_dict

register = template.Library()

@register.filter
@stringfilter
def access_code_abbreviation(code):
    '''Template filter to display an access status abbreviation from
    :class:`~keep.common.models.Rights` based on the numeric access
    status code.  Example use::

        {{ code|access_code_abbreviation }}
    
    '''
    if code in rights_access_terms_dict:
        return rights_access_terms_dict[code].abbreviation

    
