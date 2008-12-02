import logging
from django.conf import settings

from library.forms import EpubValidateForm
from library.models import SystemInfo, UserPref

log = logging.getLogger('context_processors')

stanza_browsers = ('iphone', )
 
def nav(request):
    form = EpubValidateForm()
    return {'upload_form': form }

def mobile(request):
    stanza_compatible = False
    if not hasattr(request, 'stanza_compatible') and request.META.has_key('HTTP_USER_AGENT'):
        log.debug('Checking %s for Stanza-compatibility' % request.META['HTTP_USER_AGENT']) 
        for b in stanza_browsers:
            if b in request.META["HTTP_USER_AGENT"].lower():
                log.debug('Setting true for stanza-compatible browser')
                stanza_compatible = True

    return { 'mobile': settings.MOBILE,
             'stanza_compatible': stanza_compatible}

def profile(request):
    '''Get (or create) a user preferences object for a given user.'''
    userprefs = None
    try:
        userprefs = request.user.get_profile()
        if not settings.LANGUAGE_COOKIE_NAME in request.session:
            request.session[settings.LANGUAGE_COOKIE_NAME] = userprefs.language

    except AttributeError:
        # Occurs when this is called on an anonymous user; ignore
        pass
    except UserPref.DoesNotExist:
        log.debug('Creating a userprefs object for %s' % request.user.username)
        # Create a preference object for this user
        userprefs = UserPref(user=request.user)
        userprefs.save()

    return { 'profile': userprefs }
