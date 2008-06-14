from google.appengine.api import users
from google.appengine.api import memcache
from google.appengine.ext import db

import logging, sys
from zipfile import BadZipfile

from django.http import HttpResponseRedirect, Http404, HttpResponse
from django.shortcuts import render_to_response
from django.core.urlresolvers import reverse

from models import EpubArchive, HTMLFile, UserPrefs, StylesheetFile, ImageFile, unsafe_name, get_system_info
from forms import EpubValidateForm
from epub import constants as epub_constants
from epub import InvalidEpubException


def index(request):

    common = _common(request, load_prefs=True)
    user = users.get_current_user()

    documents = EpubArchive.all()
    documents.filter('owner =', user)

    if not user:
        return render_to_response('login.html',  {'common':common,
                                                  'login':users.create_login_url('/')})

    return render_to_response('index.html', {'documents':documents, 
                                             'common':common})

def profile(request):
    common = _check_switch_modes(request)
    return render_to_response('profile.html', { 'common':common})
    

def view(request, title, author):
    logging.info("Looking up title %s, author %s" % (title, author))
    common = _check_switch_modes(request)

    document = _get_document(title, author)
    toc = HTMLFile.gql('WHERE archive = :parent ORDER BY order ASC', 
                   parent=document).fetch(100)
    
    return render_to_response('view.html', {'document':document, 
                                            'toc':toc,
                                            'common':common})

def about(request):
    common = _common(request)
    return render_to_response('about.html', {'common': common})
    

def delete(request, title, author):
    '''Delete a book and associated metadata, and decrement our total books counter'''

    logging.info("Deleting title %s, author %s" % (title, author))
    document = _get_document(title, author)

    _delete_document(document)

    return HttpResponseRedirect('/')

def profile_delete(request):
    
    userprefs = _prefs()
    userprefs.delete()

    # Decrement our total-users counter
    counter = get_system_info()
    counter.total_users -= 1
    counter.put()
    memcache.set('total_users', counter.total_users)

    # Delete all their books
    documents = EpubArchive.all()
    common = _common(request, load_prefs=True)
    user = common['user']
    documents.filter('owner =', user)

    for d in documents:
        _delete_document(d)
    
    return HttpResponseRedirect(users.create_logout_url('/'))

def _check_switch_modes(request):
    '''Did they switch viewing modes?'''
    common = _common(request, load_prefs=True)
    userprefs = common['prefs']
    update_cache = False

    if request.GET.has_key('iframe'):
        userprefs.use_iframe = (request.GET['iframe'] == 'yes')
        userprefs.put()
        update_cache = True

    if request.GET.has_key('iframe_note'):
        userprefs.show_iframe_note = (request.GET['iframe_note'] == 'yes')
        userprefs.put()
        update_cache = True

    if update_cache:
        counter = get_system_info()
        memcache.set('total_users', counter.total_users)

    return common
    
def view_chapter(request, title, author, chapter_id):
    logging.info("Looking up title %s, author %s, chapter %s" % (title, author, chapter_id))    
    document = _get_document(title, author)

    toc = HTMLFile.gql('WHERE archive = :parent ORDER BY order ASC', 
                   parent=document).fetch(100)
    chapter = HTMLFile.gql('WHERE archive = :parent AND idref = :idref',
                           parent=document, idref=chapter_id).get()


    common = _check_switch_modes(request)
        
    return render_to_response('view.html', {'common':common,
                                            'document':document,
                                            'toc':toc,
                                            'chapter':chapter})

def view_chapter_image(request, title, author, chapter_id, image):
    logging.info("Image request: looking up title %s, author %s, chapter %s, image %s" % (title, author, chapter_id, image))        
    document = _get_document(title, author)
    # Chapter is irrelevant but ends up in the request because the 
    # document's links are relative
    image = ImageFile.gql('WHERE archive = :parent AND idref = :idref',
                          parent=document, idref=image).get()
    response = HttpResponse(content_type=image.content_type)
    if image.content_type == 'image/svg+xml':
        response.content = image.file
    else:
        response.content = image.data

    return response


def view_chapter_frame(request, title, author, chapter_id):
    '''Generate an iframe to display the document online, possibly with its own stylesheets'''
    document = _get_document(title, author)
    chapter = HTMLFile.gql('WHERE archive = :parent AND idref = :idref',
                           parent=document, idref=chapter_id).get()    
    stylesheets = StylesheetFile.gql('WHERE archive = :parent',
                                     parent=document).fetch(10)
    return render_to_response('frame.html', {'document':document, 
                                             'chapter':chapter, 
                                             'stylesheets':stylesheets})

def view_stylesheet(request, title, author, stylesheet_id):
    document = _get_document(title, author)
    logging.info('getting stylesheet %s' % stylesheet_id)
    stylesheet = StylesheetFile.gql('WHERE archive = :parent AND idref = :idref',
                                    parent=document,
                                    idref=stylesheet_id).get()
    response = HttpResponse(content=stylesheet.file, content_type='text/css')
    response['Cache-Control'] = 'public'

    return response

def download_epub(request, title, author):
    document = _get_document(title, author)
    response = HttpResponse(content=document.content, content_type=epub_constants.MIMETYPE)
    response['Content-Disposition'] = 'attachment; filename=%s' % document.name
    return response

def upload(request):
    '''Uploads a new document and stores it in the datastore'''
    
    common = _common(request)
    
    document = None 
    
    if request.method == 'POST':
        form = EpubValidateForm(request.POST, request.FILES)
        if form.is_valid():

            data = form.cleaned_data['epub'].content
            document_name = form.cleaned_data['epub'].filename
            logging.info("Document name: %s" % document_name)
            document = EpubArchive(name=document_name)
            document.content = data
            document.owner = users.get_current_user()
            document.put()

            try:
                document.explode()
                document.put()
                sysinfo = get_system_info()
                sysinfo.total_books += 1
                sysinfo.put()
                # Update the cache
                memcache.set('total_books', sysinfo.total_books)

            except BadZipfile:
                logging.error('Non-zip archive uploaded: %s' % document_name)
                message = 'The file you uploaded was not recognized as an ePub archive and could not be added to your library.'
                document.delete()
                return render_to_response('upload.html', {'common':common,
                                                          'form':form, 
                                                          'message':message})
            except InvalidEpubException:
                logging.error('Non epub zip file uploaded: %s' % document_name)
                message = 'The file you uploaded was a valid zip file but did not appear to be an ePub archive.'
                document.delete()
                return render_to_response('upload.html', {'common':common,
                                                          'form':form, 
                                                          'message':message})                
            except:
                # If we got any error, delete this document
                logging.error('Got deadline exceeded error on request, deleting document')
                logging.error(sys.exc_info()[0])
                document.delete()
                raise
            
            logging.info("Successfully added %s" % document.title)
            return HttpResponseRedirect('/')

        return HttpResponseRedirect('/')

    else:
        form = EpubValidateForm()        

    return render_to_response('upload.html', {'common':common,
                                              'form':form, 
                                              'document':document})



def _delete_document(document):
    # Delete the chapters of the book
    toc = HTMLFile.gql('WHERE archive = :parent', 
                   parent=document).fetch(100)
    if toc:
        db.delete(toc)

    # Delete all the stylesheets in the book
    css = StylesheetFile.gql('WHERE archive = :parent', 
                             parent=document).fetch(100)

    if css:
        db.delete(css)

    # Delete all the images in the book
    images = ImageFile.gql('WHERE archive = :parent', 
                             parent=document).fetch(100)

    if images:
        db.delete(images)

    # Delete the book itself, and decrement our counter
    document.delete()
    sysinfo = get_system_info()
    sysinfo.total_books -= 1
    sysinfo.put() 
    memcache.set('total_books', sysinfo.total_books)

def _get_document(title, author, override_owner=False):
    '''Return a document by title, author and owner.  Setting override_owner
    will search regardless of ownership, for use with admin accounts.'''
    owner = users.get_current_user()
    title=unsafe_name(title)
    author=unsafe_name(author)

    if override_owner:
        document = EpubArchive.gql('WHERE title = :title AND authors = :authors AND owner = :owner',
                                   owner=owner,
                                   title=title,
                                   authors=author,
                                   ).get()    
    else:
        document = EpubArchive.gql('WHERE title = :title AND authors = :authors',
                                   authors=author,
                                   title=title,
                                   ).get()            
    if not document:
        logging.error("Failed to get document with title '%s'  (type %s) and author '%s' (type %s)" 
                      % (unsafe_name(title), 
                         type(unsafe_name(title)), 
                         unsafe_name(author), 
                         type(unsafe_name(author))))
        raise Http404 
        
    return document



def _greeting():
    user = users.get_current_user()
    if user:
        text = ('Signed in as %s: <a href="%s">logout</a> | <a href="%s">edit profile</a>' % 
                (user.nickname(), 
                 users.create_logout_url("/"),
                 reverse('library.views.profile')
                 )
                )
        if users.is_current_user_admin():
            text += ' | <a href="%s">admin</a> ' % reverse('library.admin.search')
        return text

    return ("<a href=\"%s\">Sign in or register</a>." % users.create_login_url("/"))


def _prefs():
    '''Get (or create) a user preferences object for a given user.
    If created, the total number of users counter will be incremented and
    the memcache updated.'''

    user = users.get_current_user()
    if not user:
        return

    q = UserPrefs.gql("WHERE user = :1", user)
    userprefs = q.get()
    if not userprefs:
        logging.info('Creating a userprefs object for %s' % user.nickname)
        # Create a preference object for this user
        userprefs = UserPrefs(user=user)
        userprefs.put()

        # Increment our total-users counter
        counter = get_system_info()

        counter.total_users += 1
        counter.put()
        memcache.set('total_users', counter.total_users)

    return userprefs

def _common(request, load_prefs=False):
    '''Builds a dictionary of common 'globals' 
    @todo cache some of this, like from sysinfo'''

    common = {}
    user = users.get_current_user()
    common['user']  = user

    # Don't load user prefs unless we need to
    if load_prefs:
        common['prefs'] = _prefs()

    cached_total_books = memcache.get('total_books')

    if cached_total_books is not None:
        common['total_books'] = cached_total_books
    else:
        sysinfo = get_system_info()
        common['total_books'] = sysinfo.total_books
        memcache.set('total_books', sysinfo.total_books)

    cached_total_users = memcache.get('total_users')

    if cached_total_users is not None:
        common['total_users'] = cached_total_users
    else:
        if not sysinfo:
            sysinfo = get_system_info()            
        common['total_users'] = sysinfo.total_users
        memcache.set('total_users', sysinfo.total_users)

    common['greeting'] = _greeting()

    common['upload_form'] = EpubValidateForm()        
    return common



    