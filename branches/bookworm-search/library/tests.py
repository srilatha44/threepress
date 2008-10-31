#!/usr/bin/env python
# encoding: utf-8
import shutil, os, re, unittest, logging
from os.path import isfile, isdir

from django.contrib.auth.models import User
from django.test import TestCase as DjangoTestCase

from models import *
from testmodels import *
from epub.toc import TOC
from epub.constants import *
import epub.util

from twill import get_browser
from twill.errors import TwillAssertionError
from twill import add_wsgi_intercept
from twill.commands import *

from django.conf import settings

settings.SITE_ID = 1

# Data for public epub documents
DATA_DIR = unicode(os.path.abspath('./library/test-data/data'))

# Local documents should be added here and will be included in tests,
# but not in the svn repository
PRIVATE_DATA_DIR = u'%s/private' % DATA_DIR

STORAGE_DIR = os.path.abspath('./library/test-data/storage')

class TestModels(unittest.TestCase):

    def setUp(self):

        # Add all our test data
        self.documents = [d for d in os.listdir(DATA_DIR) if '.epub' in d and isfile('%s/%s' % (DATA_DIR, d))]

        if isdir(PRIVATE_DATA_DIR):
            self.documents += [d for d in os.listdir(PRIVATE_DATA_DIR) if '.epub' in d and isfile('%s/%s' % (PRIVATE_DATA_DIR, d))] 

        
        self.user = User(username='testuser')
        self.user.save()
        profile = UserPref(user=self.user)
        profile.save()

    def tearDown(self):
        self.user.delete()
        for d in os.listdir(STORAGE_DIR):
            shutil.rmtree("%s/%s" % (STORAGE_DIR, d))

    def test_all_documents(self):
        '''Run through all the documents at a high level'''
        for d in self.documents:
            if d.startswith("invalid"):
                # Test bad documents here?
                pass
            else:
                doc = self.create_document(d)
                doc.explode()

    def test_title(self):
        '''Did we get back the correct title?'''
        title = u'Pride and Prejudice'
        filename = 'Pride-and-Prejudice_Jane-Austen.epub'
        document = self.create_document(filename)
        document.explode()
        self.assertEquals(title, document.title)

    def test_single_author(self):
        '''Did we get a single author from our author() method?'''
        author = u'Jane Austen'
        filename = 'Pride-and-Prejudice_Jane-Austen.epub'
        document = self.create_document(filename)
        document.explode()
        self.assertEquals(author, document.author)        

    def test_multiple_authors(self):
        '''Do we return the correct number of authors in the correct order?'''
        expected_authors = [u'First Author', u'Second Author']
        opf_file = 'two-authors.opf'
        document = MockEpubArchive(name=opf_file)
        opf = epub.util.xml_from_string(_get_file(opf_file))
        authors = [a.name for a in document.get_authors(opf)]
        self.assertEquals(expected_authors, authors)

    def test_multiple_authors_as_author(self):
        '''Multiple authors should be displayable in a short space.'''
        opf_file = 'two-authors.opf'
        expected_authors = [u'First Author', u'Second Author']
        document = MockEpubArchive(name=opf_file)
        document.owner = self.user
        document.save()
        opf = epub.util.xml_from_string(_get_file(opf_file))
        
        fuzz = 4
        len_first_author = len(expected_authors[0])
        len_short_author_str = len(document.get_author(opf))
        difference = len_short_author_str - len_first_author
        self.assert_(difference < fuzz)

    def test_no_author(self):
        '''An OPF document with no authors should return None.'''
        no_author_opf_file = 'no-author.opf'
        no_author_document = MockEpubArchive(name=no_author_opf_file)
        no_author_document.owner = self.user
        no_author_document.save()

        opf = epub.util.xml_from_string(_get_file(no_author_opf_file))

        author = no_author_document.get_author(opf)
        self.failIf(author)

    def test_no_author_document(self):
        '''A full document should still pass explode() if there is an empty author'''
        a = self.create_document('No-Author.epub')
        a.explode()

    def test_create_document(self):
        '''Assert that we created a non-None document.'''
        d = self.create_document(self.documents[0])
        self.assert_(d)

    def test_find_document(self):
        """Documents should be findable by title"""
        title = u'Pride and Prejudice'
        filename = 'Pride-and-Prejudice_Jane-Austen.epub'
        document = self.create_document(filename)
        document.explode()
        document.save()
        d = _get_document(title, document.id)
        self.failUnless(d)

    def test_bad_epub_fails(self):
        """ePub documents with missing compontent should raise errors."""
        filename = 'invalid_no_container.epub'
        document = self.create_document(filename)
        self.assertRaises(InvalidEpubException, document.explode)

    def test_safe_name(self):
        """Names should be safely quoted for URLs."""
        name = u'John Q., CommasAreForbidden'
        sn = safe_name(name)
        comma_re = re.compile(",")
        result = comma_re.match(sn)
        self.failIf(result)

    def test_count_toc(self):
        '''Check that in a simple document, the number of chapter items equals the number of top-level nav items'''
        filename = 'Pride-and-Prejudice_Jane-Austen.epub'
        document = self.create_document(filename)
        document.explode()
        document.save()

        toc = TOC(document.toc)
        self.failUnless(toc)

        chapters = HTMLFile.objects.filter(archive=document)
        self.assertEquals(len(chapters), len(toc.find_points(1)))

    def test_no_toc_in_item(self):
        '''Test an OPF file that has no <item> reference to a TOC'''
        filename = 'Pride-and-Prejudice_Jane-Austen.epub'
        opf = _get_file('no-toc-item.opf')
        document = self.create_document(filename)        
        document.explode()
        parsed_opf = util.xml_from_string(opf)
        items = [i for i in parsed_opf.iterdescendants(tag="{%s}item" % (NS['opf']))]
        try:
            document._get_toc(parsed_opf, items, 'OEBPS')
        except InvalidEpubException:
            err = str(sys.exc_info()[1])
            self.assertTrue('Could not find an item' in err)
            return
        self.assert_(False)

    def test_no_toc_attribute(self):
        '''Test an OPF file that has no @toc in the <spine>'''
        filename = 'Pride-and-Prejudice_Jane-Austen.epub'
        opf = _get_file('no-toc-attribute-in-spine.opf')
        document = self.create_document(filename)        
        document.explode()
        parsed_opf = util.xml_from_string(opf)
        items = [i for i in parsed_opf.iterdescendants(tag="{%s}item" % (NS['opf']))]
        try:
            document._get_toc(parsed_opf, items, 'OEBPS')
        except InvalidEpubException:
            err = str(sys.exc_info()[1])
            logging.info(err)
            self.assertTrue('Could not find toc attribute' in err)
            return
        self.assert_(False)

    def test_no_toc(self):
        '''Test an OPF file that has has a TOC reference to a nonexistent file'''
        filename = 'invalid-no-toc.epub'
        document = self.create_document(filename)        
        document.save()
        try:
            document.explode()
        except InvalidEpubException:
            err = str(sys.exc_info()[1])
            self.assertTrue('TOC file was referenced in OPF, but not found in archive' in err)
            return
        self.assert_(False)

        
    def test_first_item_in_toc(self):
        '''Check that the first_item method returns the correct item based on the rules
        defined in the OCF spec.'''
        toc = TOC(_get_file('top-level-toc.ncx'), 
                  _get_file('linear-no-missing-linear.opf'))
        first = toc.first_item()
        self.assert_(first)
        self.assertEquals('htmltoc', first.id)

        toc = TOC(_get_file('top-level-toc.ncx'), 
                  _get_file('linear-no.opf'))
        first = toc.first_item()
        self.assert_(first)
        self.assertEquals('htmltoc', first.id)

    def test_aux_toc(self):
        '''Support one or more lists of additional content'''
        toc = TOC(_get_file('auxilliary-lists.ncx'))

        aux1 = toc.lists[0]
        self.assert_(aux1)

        aux2 = toc.lists[1]
        self.assert_(aux2)
        
        self.assertEquals(2, len(toc.lists))
        self.assertEquals(2, len(aux1.tree))
        self.assertEquals(3, len(aux2.tree))
        self.assertEquals('recipe 2', aux2.tree[1].label)
        self.assertEquals('image1.html', aux1.tree[0].href())

    def test_count_deep_toc(self):
        '''Check a complex document with multiple nesting levels'''
        toc = TOC(_get_file('complex-ncx.ncx'))
        self.failUnless(toc)
        self.assert_(len(toc.find_points(3)) > len(toc.find_points(2)) > len(toc.find_points(1)))

    def tests_ordered_toc(self):
        '''TOC should preserve the playorder of the NCX'''
        toc = TOC(_get_file('complex-ncx.ncx'))
        self.failUnless(toc)
        # First item is the Copyright statement, which has no children
        copyright_statement = toc.tree[0]
        self.assertEquals(copyright_statement.title(), 'Copyright')

        # Second item should be the preface 
        preface = toc.tree[1]
        self.assertEquals(preface.title(), 'Preface')        

        # Last item is the Colophon
        colophon = toc.tree[-1:][0]
        self.assertEquals(colophon.title(), 'Colophon')

    def test_find_children(self):
        '''Get the children of a particular nested TOC node, by node'''
        toc = TOC(_get_file('complex-ncx.ncx'))
        self.failUnless(toc)

        # First item is the Copyright statement, which has no children
        copyright_section = toc.tree[0]
        children = toc.find_children(copyright_section)
        self.failIf(children)

        # Second item is the Preface, which has 8 children
        preface = toc.tree[1]
        children = toc.find_children(preface)
        self.assertEquals(8, len(children))

    def test_find_descendants(self):
        '''Get the deep children of a particular nested TOC'''
        toc = TOC(_get_file('complex-ncx.ncx'))
        chapter = toc.tree[11]
        ancestors = chapter.find_ancestors()
        self.assertNotEquals(0, len(ancestors))

        intro = toc.tree[10]
        self.assertEquals('pt01.html', intro.href())
        self.assertEquals(intro.id, ancestors[0].id)

        descendants = toc.find_descendants(chapter)
        self.assertEquals(30, len(descendants))

    def test_toc_href(self):
        '''Ensure that we are returning the correct href for an item'''
        toc = TOC(_get_file('complex-ncx.ncx'))
        preface = toc.tree[1]
        self.assertEquals("pr02.html", preface.href())

    def test_toc_top_level(self):
        '''We should use the <spine> to locate the top-level navigation items'''
        toc = TOC(_get_file('top-level-toc.ncx'), 
                  _get_file('top-level-toc.opf'))
        first_page_ncx = toc.tree[0]  
        first_page_spine = toc.items[0]
        self.assertNotEquals(first_page_ncx.label,
                             first_page_spine.label)

    def test_get_file_by_item(self):
        '''Make sure we can find any item by its idref'''
        filename = 'Pride-and-Prejudice_Jane-Austen.epub'
        document = self.create_document(filename)
        document.explode()
        document.save()
        self.assert_(document.opf)
        toc = document.get_toc()
        self.assert_(toc)
        self.assert_(len(toc.items) > 0)
        item = toc.items[2]
        self.assertEquals(item.id, 'chapter-3')
        self.assertEquals(item.media_type, 'application/xhtml+xml')
        self.assertEquals(item.media_type, XHTML_MIMETYPE)
        f = get_file_by_item(item, document)
        self.assertEquals(f.filename, 'chapter-3.html')

    def test_toc_next_previous_item(self):
        filename = 'Pride-and-Prejudice_Jane-Austen.epub'
        document = self.create_document(filename)
        document.explode()
        document.save()
        toc = document.get_toc()
        item = toc.items[2]
        self.assertEquals(item.id, 'chapter-3')
        item2 = toc.find_next_item(item)
        self.assertEquals(item2.id, 'chapter-4')        
        item3 = toc.find_previous_item(item2)
        self.assertEquals(item.id, item3.id)


    def test_metadata(self):
        '''All metadata should be returned using the public methods'''
        opf_file = 'all-metadata.opf'
        document = MockEpubArchive(name=opf_file, owner=self.user)
        opf = _get_file(opf_file)

        self.assertEquals('en-US', document.get_metadata(DC_LANGUAGE_TAG, opf))
        self.assertEquals('Public Domain', document.get_metadata(DC_RIGHTS_TAG, opf))
        self.assertEquals('threepress.org', document.get_metadata(DC_PUBLISHER_TAG, opf))
        self.assertEquals(3, len(document.get_metadata(DC_SUBJECT_TAG, opf)))
        self.assertEquals('Subject 1', document.get_metadata(DC_SUBJECT_TAG, opf)[0])
        self.assertEquals('Subject 2', document.get_metadata(DC_SUBJECT_TAG, opf)[1])
        self.assertEquals('Subject 3', document.get_metadata(DC_SUBJECT_TAG, opf)[2])

        self.assertEquals('en-US', document.get_language())
        self.assertEquals('Public Domain', document.get_rights())
        self.assertEquals('threepress.org', document.get_publisher().all()[0].name)

        document.get_subjects()

        # Test new database methods
        self.assertEquals('en-US', document.language)
        self.assertEquals('Public Domain', document.rights)
        self.assertEquals('threepress.org', document.publishers.all()[0].name)
        self.assertEquals('Subject 1', document.subjects.get(name='Subject 1').name)
        self.assertEquals('Subject 2', document.subjects.get(name='Subject 2').name)
        self.assertEquals('Subject 3', document.subjects.get(name='Subject 3').name)
    
    def test_publishers(self):
        name = 'Oxford University Press'
        p = EpubPublisher.objects.get_or_create(name=name)[0]
        p.save()
        p2 = EpubPublisher.objects.get(name=name)
        self.assertEquals(p2.name, name)

    def test_subjects(self):
        name = 'Health'
        s = Subject.objects.get_or_create(name=name)[0]
        s.save()
        s2 = Subject.objects.get(name=name)
        self.assertEquals(s2.name, name)


    def test_invalid_xhtml(self):
        '''Documents with non-XML content should be renderable'''
        document = self.create_document('invalid-xhtml.epub')
        document.explode()
        document.save()
        chapters = HTMLFile.objects.filter(archive=document)
        self.assert_(len(chapters) > 0)
        for c in chapters:
            c.render()

    def test_html_entities(self):
        '''Documents which are valid XML except for HTML entities should convert'''
        document = self.create_document('html-entities.epub')
        document.explode()
        document.save()
        chapters = HTMLFile.objects.filter(archive=document)
        self.assert_(len(chapters) > 0)
        for c in chapters:
            c.render()        

    def test_utf8_document(self):
        '''This document has both UTF-8 characters in it and UTF-8 filenames'''
        document = self.create_document(u'天.epub')
        document.explode()
        document.save()
        chapters = HTMLFile.objects.filter(archive=document)
        self.assert_(len(chapters) > 0)
        for c in chapters:
            c.render()        
        
    def test_remove_html_namespaces(self):
        filename = 'Cory_Doctorow_-_Little_Brother.epub'        
        document = self.create_document(filename)
        document.explode()
        document.save()
        chapters = HTMLFile.objects.filter(archive=document)
        self.assert_('html:br' not in chapters[0].render())

    def test_remove_body_tag(self):
        '''We should not be printing the original document's <body> tag'''
        filename = 'Pride-and-Prejudice_Jane-Austen.epub'
        document = self.create_document(filename)
        document.explode()
        document.save()
        chapters = HTMLFile.objects.filter(archive=document)
        self.assert_(len(chapters) == 61)
        for c in chapters:
            self.assert_('<body' not in c.render())
            self.assert_('<div id="bw-book-content"' in c.render())


        
    def test_chapters(self):
        '''When switching to lxml, chapters in this book did not get captured'''
        filename = 'Cory_Doctorow_-_Little_Brother.epub'
        document = self.create_document(filename)
        document.explode()
        document.save()
        chapters = HTMLFile.objects.filter(archive=document)
        self.assert_(chapters)
        
    def test_binary_image(self):
        '''Test the ImageBlob class directly'''
        filename = 'Pride-and-Prejudice_Jane-Austen.epub'
        document = self.create_document(filename)
        document.explode()
        document.save()
        imagename = 'alice01a.gif'
        image = _get_file(imagename)
        image_obj = MockImageFile(idref=imagename,
                              archive=document)
        image_obj.save()

        i = MockImageBlob(archive=document,
                      idref=imagename,
                      image=image_obj,
                      data=image,
                      filename=imagename)
        i.save()
        i2 = MockImageBlob.objects.filter(idref=imagename)[0]
        self.assertEquals(image, i2.get_data())
        i2.delete()

    def test_binary_image_autosave(self):
        '''Test that an ImageFile creates a blob and can retrieve it'''
        filename = 'Pride-and-Prejudice_Jane-Austen.epub'
        document = self.create_document(filename)
        document.explode()
        document.save()
        imagename = 'alice01a.gif'
        image = _get_file(imagename)
        image_obj = MockImageFile(idref=imagename,
                              archive=document,
                              data=image)
        image_obj.save()
        i2 = MockImageFile.objects.filter(idref=imagename)[0]
        self.assertEquals(image, i2.get_data())
        i2.delete()
        
    def test_binary_image_autodelete(self):
        '''Test that an ImageFile can delete its associated blob'''
        filename = 'Pride-and-Prejudice_Jane-Austen.epub'
        document = self.create_document(filename)
        document.explode()
        document.save()
        imagename = 'alice2.gif'
        image = _get_file(imagename)
        image_obj = MockImageFile(idref=imagename,
                              archive=document,
                              data=image)
        image_obj.save()
        i2 = MockImageFile.objects.filter(idref=imagename)[0]
        storage = i2._blob()._get_file()
        self.assert_(storage)
        i2.delete()
        self.assert_(not os.path.exists(storage))


    def test_image_with_path_info(self):
        filename = 'alice-fromAdobe.epub'
        document = self.create_document(filename)
        document.explode()
        document.save()
        
        i = MockImageFile.objects.filter(archive=document)[0]
        self.assertEquals(u'images', i.path)



    def test_binary_epub(self):
        '''Test the storage of an epub binary'''
        filename = 'Pride-and-Prejudice_Jane-Austen.epub'
        document = self.create_document(filename)
        document.explode()
        document.save()
        epub = _get_file(filename)
        bin = MockEpubBlob(idref=filename,
                       archive=document,
                       filename=filename,
                       data=epub)
        bin.save()
        b2 = MockEpubBlob.objects.filter(idref=filename)[0]

        # Assert that we can read the file, and it's the same
        self.assertEquals(epub, b2.get_data())

        # Assert that it's physically in the storage directory
        storage = b2._get_file()
        self.assert_(os.path.exists(storage))        

        # Assert that once we've deleted it, it's gone
        b2.delete()
        self.assert_(not os.path.exists(storage))        

    def test_safe_deletion_when_epub_gone(self):
        '''If an epub binary is deleted, we should still allow deletion from the database'''
        filename = 'Pride-and-Prejudice_Jane-Austen.epub'
        document = self.create_document(filename)
        document.explode()
        document.save()
        epub = _get_file(filename)
        bin = MockEpubBlob(idref=filename,
                       archive=document,
                       filename=filename,
                       data=epub)
        bin.save()
        b2 = MockEpubBlob.objects.filter(idref=filename)[0]        
        self.assert_(b2)
        b2.delete()
        try:
            document.delete()
        except InvalidBinaryException:
            pass
        
    def test_opf_file_in_subdir(self):
        '''A archive should be able to put its OPF file in a subdirectory and still locate the resources'''
        filename = 'opf-in-subdirectory.epub'
        document = self.create_document(filename)
        document.explode()
        document.save()
        self.assertEquals('OPF in subdir', document.title)

    def test_no_title_in_opf(self):
        '''Documents without titles should return a helpful error rather than crash'''
        filename = 'no-title.opf'
        document = MockEpubArchive(name=filename)
        opf = _get_file(filename)
        parsed_opf = util.xml_from_string(opf)
        try:
            document.get_title(parsed_opf)
        except InvalidEpubException:
            return
        raise Exception('Failed to get invalid epub exception for title')

    def test_blank_title_in_opf(self):
        '''Documents without titles should return a helpful error rather than crash'''
        filename = 'blank-title.opf'
        document = MockEpubArchive(name=filename)
        opf = _get_file(filename)
        parsed_opf = util.xml_from_string(opf)
        try:
            document.get_title(parsed_opf)
        except InvalidEpubException:
            return
        raise Exception('Failed to get invalid epub exception for title')

    def test_read_chapter(self):
      
        filename = 'Pride-and-Prejudice_Jane-Austen.epub'
        document = self.create_document(filename)
        document.user = self.user
        document.explode()
        document.save()
        chapter = HTMLFile.objects.filter(archive=document)[0]
        chapter.read()
        document = EpubArchive.objects.get(name=filename)
        self.assertEquals(chapter, document.last_chapter_read)

        # Try rendering, then check that the last one is up-to-date
        chapter2 = HTMLFile.objects.filter(archive=document)[1]
        chapter2.render()
        document = EpubArchive.objects.get(name=filename)
        self.assertEquals(chapter2, document.last_chapter_read)

        chapter3 = HTMLFile.objects.filter(archive=document)[1]
        self.assertTrue(chapter3.is_read)

    def test_allow_no_playorder_in_toc(self):
        '''Assert that if we have no playOrder we can fall back to document order'''
        filename = 'no-playorder.ncx'
        f = _get_file(filename)
        toc = TOC(f)
        point = toc.find_points()[0]
        self.assertEquals(1, point.order())
        point = toc.find_points()[1]
        self.assertEquals(4, point.order())

    def test_rights_document(self):
        '''Assert that we correctly recognize a rights-managed epub'''
        filename = 'invalid-rights-managed.epub'
        document = self.create_document(filename)
        document.user = self.user
        self.assertRaises(DRMEpubException, document.explode)

        filename = 'Pride-and-Prejudice_Jane-Austen.epub'
        document = self.create_document(filename)
        document.user = self.user
        document.explode()

    def test_identifier_type(self):
        '''Test that we return the correct identifier type'''
        filename = 'Pride-and-Prejudice_Jane-Austen.epub'
        document = self.create_document(filename, identifier='urn:isbn:9780596528102')
        self.assertEquals(document.identifier_type(), IDENTIFIER_ISBN)

        document = self.create_document(filename, identifier='9780061734335')
        self.assertEquals(document.identifier_type(), IDENTIFIER_ISBN_MAYBE)

        document = self.create_document(filename, identifier='urn:uuid:e100da66-666a-11dd-b455-001cc05a7670')
        self.assertEquals(document.identifier_type(), IDENTIFIER_UUID)

        document = self.create_document(filename, identifier='xyzzy')
        self.assertEquals(document.identifier_type(), IDENTIFIER_UNKNOWN)

        document = self.create_document(filename, identifier='http://www.snee.com/epub/pg23598')
        self.assertEquals(document.identifier_type(), IDENTIFIER_URL)
        
    def create_document(self, document, identifier=''):
        epub = MockEpubArchive(name=document)
        epub.identifier = identifier
        epub.owner = self.user
        epub.save()
        epub.set_content(_get_file(document))

        return epub

    
class TestViews(DjangoTestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser",email="test@example.com",password="testuser")
        self.user.save()        
        profile = UserPref(user=self.user)
        profile.save()

    def tearDown(self):
        self.user.delete()

    def test_is_inner_path_protected(self):
        self._login()
        self.client.logout()
        response = self.client.get('/view/test/1/')
        self.assertRedirects(response, '/account/signin/?next=/view/test/1/', 
                             status_code=302, 
                             target_status_code=200)

    def test_home_unprotected(self):
        '''Index should now be accessible'''
        response = self.client.get('/')
        self.assertTemplateUsed(response, 'public.html')

    def test_login(self):
        self._login()
        response = self.client.get('/')
        self.assertTemplateUsed(response, 'index.html')
        self.assertContains(response, 'testuser')

    def _login(self):
        self.assertTrue(self.client.login(username='testuser', password='testuser'))

    def test_upload(self):
        response = self._upload('Pride-and-Prejudice_Jane-Austen.epub')
        self.assertRedirects(response, '/', 
                             status_code=302, 
                             target_status_code=200)


    def _upload(self, f):
        self._login()
        fh = _get_filehandle(f)
        response = self.client.post('/upload/', {'epub':fh})
        return response

    def test_upload_invalid_epub(self):
        response = self._upload('invalid-no-toc.epub')
        self.assertTemplateUsed(response, 'upload.html')
        self.assertContains(response, 'TOC file was referenced in OPF, but not found in archive')
        # Check that we talked to epubcheck too
        self.assertContains(response, 'agrees that')
        self.assertContains(response, 'toc-doesnt-exist.ncx is missing')

    def test_content_visible(self):
        response = self._upload('Cory_Doctorow_-_Little_Brother.epub')

        id = '1'
        self.assert_(id)
        response = self.client.get('/view/Little-Brother/%s/main5.xml' % id)
        self.assertTemplateUsed(response, 'view.html')

    def test_upload_with_nested_urls(self):
        response = self._upload('Bible.epub')
        self.assertRedirects(response, '/', 
                             status_code=302, 
                             target_status_code=200)        
        id = '1'
        response = self.client.get('/view/The+Bible/%s/Genesis/Genesis3.html' % id)
        self.assertTemplateUsed(response, 'view.html')

    def test_upload_with_images(self):
        ''' Image uploads should work whether or not their path is specified'''
        response = self._upload('alice-fromAdobe.epub')
        self.assertRedirects(response, '/', 
                             status_code=302, 
                             target_status_code=200)        
        response = self.client.get('/view/alice/1/images/alice01a.gif')
        self.assertEquals(response.status_code, 200)

        response = self.client.get('/view/alice/1/alice01a.gif')
        self.assertEquals(response.status_code, 200)

    def test_upload_with_pathless_image(self):
        response = self._upload(u'天.epub')
        self.assertRedirects(response, '/', 
                             status_code=302, 
                             target_status_code=200)        

        response = self.client.get('/view/chinese/1/cover.jpg')
        self.assertEquals(response.status_code, 200)

        response = self.client.get('/view/chinese/1/www/cover.jpg')
        self.assertEquals(response.status_code, 200)

    def test_upload_no_title(self):
        response = self._upload('invalid-no-title.epub')
        self.assertTemplateUsed(response, 'upload.html')
        self.assertContains(response, 'This ePub document does not have a title.')
        


    def test_next_previous(self):
        '''Assert that we can move next and previous through our list of books'''
        # Load enough books to exceed our settings pagination label
        for a in range(1, (settings.DEFAULT_NUM_RESULTS * 2) ):
            response = self._upload('Cory_Doctorow_-_Little_Brother.epub')
            self.assertRedirects(response, '/', 
                                 status_code=302, 
                                 target_status_code=200)        

        response = self.client.get('/')
        self.assertContains(response, 'Page 1 of 2')
        self.assertContains(response, 'date added to your library')
        self.assertContains(response, 'descending')

        response = self.client.get('/page/2')
        self.assertTemplateUsed(response, 'index.html')
        self.assertContains(response, 'Page 2 of 2')

        response = self.client.get('/page/1')
        self.assertTemplateUsed(response, 'index.html')
        self.assertContains(response, 'Page 1 of 2')

        # Going to an incorrect range should redirect us back to the first page
        response = self.client.get('/page/99')
        self.assertRedirects(response, '/page/1',
                             status_code=302,
                             target_status_code=200)

    def test_ordering(self):
        '''Test our re-ordering of books'''
        # Load enough books to exceed our settings pagination label
        for a in range(1, (settings.DEFAULT_NUM_RESULTS * 2) ):
            response = self._upload('Cory_Doctorow_-_Little_Brother.epub')
            self.assertRedirects(response, '/', 
                                 status_code=302, 
                                 target_status_code=200)        
        
        response = self.client.get('/')
        self.assertContains(response, 'Page 1 of 2')

        response = self.client.get('/page/1/order/title/dir/asc')
        self.assertContains(response, 'Page 1 of 2')
        self.assertContains(response, 'book title')
        self.assertContains(response, 'alphabetically')
        self.assertContains(response, 'ascending')

        response = self.client.get('/page/1/order/orderable_author/dir/asc')
        self.assertContains(response, 'Page 1 of 2')
        self.assertContains(response, 'first author')
        self.assertContains(response, 'alphabetically')
        self.assertContains(response, 'ascending')

        response = self.client.get('/page/1/order/created_time/dir/desc')
        self.assertContains(response, 'Page 1 of 2')
        self.assertContains(response, 'date added')
        self.assertContains(response, 'by date')
        self.assertContains(response, 'descending')



    def test_upload_with_utf8(self):
        response = self._upload('The-Adventures-of-Sherlock-Holmes_Arthur-Conan-Doyle.epub')
        self.assertRedirects(response, '/', 
                             status_code=302, 
                             target_status_code=200)        

        # Make sure it's in the list
        response = self.client.get('/')
        self.assertContains(response, 'Sherlock')

    def test_delete_with_utf8(self):
        response = self._upload('The-Adventures-of-Sherlock-Holmes_Arthur-Conan-Doyle.epub')
        # Make sure it's in the list
        response = self.client.get('/')
        self.assertContains(response, 'Sherlock')

        response = self.client.post('/delete/', { 'title':'The+Adventures+of+Sherlock+Holmes',
                                       'key':'1'})
        self.assertRedirects(response, '/', 
                             status_code=302, 
                             target_status_code=200)   
        response = self.client.get('/')
        self.assertNotContains(response, 'Sherlock')


    def test_upload_with_entities(self):
        response = self._upload('html-entities.epub')
        self.assertRedirects(response, '/', 
                             status_code=302, 
                             target_status_code=200)   

    def test_view_document(self):
        self._upload('Pride-and-Prejudice_Jane-Austen.epub')
        response = self.client.get('/view/Pride-and-Prejudice/1/')
        self.assertTemplateUsed(response, 'view.html')
        self.assertContains(response, 'Pride and Prejudice', status_code=200)

    def test_view_chapter(self):
        self._upload('Pride-and-Prejudice_Jane-Austen.epub')
        response = self.client.get('/view/Pride-and-Prejudice/1/chapter-1.html')
        self.assertTemplateUsed(response, 'view.html')
        self.assertContains(response, 'It is a truth universally acknowledged', status_code=200)

    def test_view_svg(self):
        self._upload('EPUBBestPractices-1_0_2.epub')
        response = self.client.get('/view/EPUB+Best+Practices/1/Container_(OCF).xhtml')
        self.assertTemplateUsed(response, 'view.html')
        self.assertContains(response, 'View linked image in SVG format')
        response = self.client.get('/view/EPUB+Best+Practices/1/images/OPS.svg')
        self.assertEquals(response.status_code, 200)

    def test_delete_book(self):
        self._upload('Pride-and-Prejudice_Jane-Austen.epub')        
        response = self.client.post('/delete/', { 'title':'Pride+and+Prejudice',
                                       'key':'1'})
        self.assertRedirects(response, '/', 
                             status_code=302, 
                             target_status_code=200)   
        
    def test_view_profile(self):
        self._login()
        response = self.client.get('/account/profile/')
        self.assertTemplateUsed(response, 'auth/profile.html')
        self.assertContains(response, 'testuser', status_code=200)        

    def test_view_about_not_logged_in(self):
        '''This throws an exception if the user profile isn't properly handled for anonymous requests'''
        response = self.client.get('/about/')
        self.assertContains(response, 'About', status_code=200)                
        self.assertTemplateUsed(response, 'about.html')

    def test_register_standard(self):
        '''Register a new account using a standard Django account'''
        response = self.client.post('/account/signup/', { 'username':'registertest',
                                                          'email':'registertest@example.com',
                                                          'password1':'registertest',
                                                          'password2':'registertest'})
        self.assertRedirects(response, '/', 
                             status_code=302, 
                             target_status_code=200)   
        response = self.client.get('/')
        self.assertTemplateUsed(response, 'index.html')
        self.assertContains(response, 'registertest', status_code=200)

    def test_change_email(self):
        '''Change the email address in a standard Django account'''
        self.test_register_standard()
        response = self.client.post('/account/email/', { 'password':'registertest',
                                                         'email':'registertest2@example.com'})
        self.assertRedirects(response, '/account/profile/?msg=Email+changed.', 
                             status_code=302, 
                             target_status_code=200)           
        
        response = self.client.get('/account/profile/')
        self.assertContains(response, 'registertest2@example.com', status_code=200)
        self.assertNotContains(response, 'registertest@example.com', status_code=200)

    def test_change_password(self):
        '''Change a standard Django account password'''
        self.test_register_standard()
        response = self.client.post('/account/password/', { 'oldpw':'registertest',
                                                            'password1':'registertest2',
                                                            'password2':'registertest2'})
        
        self.assertRedirects(response, '/account/profile/?msg=Password+changed.', 
                             status_code=302, 
                             target_status_code=200)   
        response = self.client.get('/')
        self.assertContains(response, 'registertest', status_code=200)
        self.client.logout()
        self.assertTrue(self.client.login(username='registertest', password='registertest2'))        
        self.client.logout()
        self.assertFalse(self.client.login(username='registertest', password='registertest'))        

    def test_delete_account(self):
        self.test_register_standard()
        response = self.client.post('/account/delete/', { 'password':'registertest',
                                                          'confirm':'checked'})
        
        self.assertRedirects(response, '/?msg=Your+account+has+been+deleted.',
                             status_code=302, 
                             target_status_code=200)   
        response = self.client.get('/view/test/1/')
        self.assertRedirects(response, '/account/signin/?next=/view/test/1/', 
                             status_code=302, 
                             target_status_code=200)   
        self.assertFalse(self.client.login(username='registertest', password='registertest'))                


    def test_open_to_last_chapter(self):
        self._upload('Pride-and-Prejudice_Jane-Austen.epub')

        uprofile = UserPref.objects.get(user=self.user)
        uprofile.open_to_last_chapter = True
        uprofile.save()

        response = self.client.get('/view/Pride-and-Prejudice/1/')
        self.assertTemplateUsed(response, 'view.html')        
        first_page = response.content

        # Read a page somewhere in the document
        response = self.client.get('/view/Pride-and-Prejudice/1/chapter-10.html')
        self.assertTemplateUsed(response, 'view.html')
        last_chapter_content = response.content

        # Now go to the default page; should be last chapter
        response = self.client.get('/view/Pride-and-Prejudice/1/')
        self.assertTemplateUsed(response, 'view.html')        
        self.assertEquals(last_chapter_content, response.content)

        # Now change our user profile to not select this behavior
        uprofile.open_to_last_chapter = False
        uprofile.save()

        response = self.client.get('/view/Pride-and-Prejudice/1/')
        self.assertTemplateUsed(response, 'view.html')        
        self.assertNotEquals(last_chapter_content, response.content)        
        self.assertEquals(first_page, response.content)

        # But we should still be able to force it with the resume parameter
        response = self.client.get('/view/Pride-and-Prejudice/1/chapter-10.html')
        self.assertTemplateUsed(response, 'view.html')
        last_chapter_content = response.content

        response = self.client.get('/view/Pride-and-Prejudice/1/resume/')
        self.assertTemplateUsed(response, 'view.html')        
        self.assertEquals(last_chapter_content, response.content)        
        self.assertNotEquals(first_page, response.content)        

    def test_force_first_page(self):
        self._upload('Pride-and-Prejudice_Jane-Austen.epub')

        uprofile = UserPref.objects.get(user=self.user)
        uprofile.open_to_last_chapter = True
        uprofile.save()

        response = self.client.get('/view/Pride-and-Prejudice/1/')
        self.assertTemplateUsed(response, 'view.html')        
        first_page = response.content

        # Read a page somewhere in the document
        response = self.client.get('/view/Pride-and-Prejudice/1/chapter-10.html')
        self.assertTemplateUsed(response, 'view.html')
        last_chapter_content = response.content

        # Force first chapter chapter
        response = self.client.get('/view/Pride-and-Prejudice/1/first/')
        self.assertTemplateUsed(response, 'view.html')        
        self.assertEquals(first_page, response.content)        


    def test_search_form(self):
        name = 'Pride-and-Prejudice_Jane-Austen.epub'
        self._upload(name)
        from bookworm.search import epubindexer
        epub = EpubArchive.objects.get(name=name)
        epubindexer.index_epub(self.user.username, epub)
        res = self.client.get('/search/', { 'q' : 'lizzy',
                                            'language': 'en'})
        self.assertTemplateUsed(res, 'results.html')
        self.assertContains(res, 'My dear')
        res = self.client.get('/search/', { 'q' : 'lizzy',
                                            'language': 'en',
                                            'start': '20',
                                            'end': '40'})        
        self.assertTemplateUsed(res, 'results.html')
        self.assertContains(res, 'dearest')        
class TestTwill(DjangoTestCase):
    def setUp(self):
        os.environ["DJANGO_SETTINGS_MODULE"] = "settings"
        
        from django.core.servers.basehttp import AdminMediaHandler
        from django.core.handlers.wsgi import WSGIHandler

        app = AdminMediaHandler(WSGIHandler())
        add_wsgi_intercept("127.0.0.1", 9876, lambda: app)
        self.b = get_browser()
        #if 'threepress' in gethostname():
        #    self.url = 'http://bookworm.threepress.org/'
        #else:
        #    self.url = 'http://127.0.0.1:9876'
        self.url = 'http://127.0.0.1:9876'
        #self.url = 'http://localhost:8000'

    def test_home(self):
        go(self.url)
        url('/')

    def test_register(self):
        self._register()

    def test_upload(self):
        self._register()
        #self._login()
        go(self.url)
        formfile("upload", "epub", _get_filepath('Pride-and-Prejudice_Jane-Austen.epub'))
        submit("submit-upload")
        find('Pride and Prejudice')

    def _login(self):
        go('/account/signin/')
        fv("fauth", "username", "twilltest")
        fv("fauth", "password", "twill")
        submit()


    def _register(self):
        go(self.url)
        follow('register')

        url('signup')
        fv("2", "username", "twilltest")
        fv("2", "email", "twilltest@example.com")
        fv("2", "password1", "twill")
        fv("2", "password2", "twill")
        submit("register_local")
        url("/$")
        find("twilltest")
        
    def tearDown(self):
        pass


        
def _get_document(title, id):
    '''@todo Mock this out better instead of overwriting the real view'''
    return MockEpubArchive(id=id)

def _get_file(f):
    '''Get a file from either the public or private data directories'''
    return _get_filehandle(f).read()

def _get_filehandle(f):
    '''Get a file from either the public or private data directories'''
    path = _get_filepath(f)
    return open(path)

def _get_filepath(f):
    data_dir = u'%s/%s' % (DATA_DIR, f)
    if os.path.exists(data_dir):
        return data_dir

    data_dir = u'%s/%s' % (PRIVATE_DATA_DIR, f)
    if os.path.exists(data_dir):
        return data_dir    
    raise OSError('Could not find file %s in either data dir' % f)


if __name__ == '__main__':
    logging.error('Invoke this using "manage.py test"')