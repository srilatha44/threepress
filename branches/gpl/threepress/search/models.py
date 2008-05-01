from django.db import models
from django.db.models import permalink
from lxml import etree
from StringIO import StringIO
import xapian
from threepress import settings
from lxml import etree

TEI = 'http://www.tei-c.org/ns/1.0'    
TEI_XSLT = etree.XSLT(etree.parse('%s/data/xsl/tei-xsl-5.9/p5/xhtml/tei.xsl'  % (settings.DIR_ROOT)))

class Document(models.Model):
    id      = models.CharField(max_length=1000, primary_key=True)
    title   = models.CharField(max_length=2000)
    author  = models.CharField(max_length=2000)
    pub_date = models.DateTimeField('date published')
    add_date = models.DateTimeField('date added')

    # Documents may have content because they have no chapters/parts, or have
    # front matter
    content = models.TextField()

    def has_parts(self):
        if len(self.part_set.all()) > 0:
            return True
        return False

    @permalink
    def get_absolute_url(self):
        return ('threepress.search.views.document_view', [self.id])

    def link(self, text=None):
        if not text:
            text = self.title
        return '<a href="%s">%s</a>' % (self.get_absolute_url(), self.title)

    def info(self):
        if len([p for p in self.part_set.all()]) > 1:
            parts_text = "%d parts with " % (len([p for p in self.part_set.all()]))
        else:
            parts_text = ""
        if len([p for p in self.chapter_set.all()]) > 1:        
            return "%s %d chapters" % (parts_text, len([p for p in self.chapter_set.all()]))
        return ""

    def __unicode__(self):
        return "%s by %s" % ( self.title, self.author)

    class Meta: 
        ordering = ['title', 'author', '-pub_date']

    class Admin:
        pass

class Part(models.Model):
    id      = models.CharField(max_length=1000, primary_key=True)
    document = models.ForeignKey(Document, max_length=1000)

    # Label, e.g. "part" or "book"
    label = models.CharField(max_length=2000)
    title = models.CharField(max_length=2000)

    # Parts may have content which doesn't fall into a chapter
    content = models.TextField()

    # Which part is this, in order?
    ordinal = models.PositiveIntegerField(default=1)


    def __unicode__(self):
        return "%s: %s (%d)" % (self.label, self.title, self.ordinal)

    class Meta:
        ordering = ['ordinal']

    class Admin:
        pass


class Chapter(models.Model):
    id      = models.CharField(max_length=1000, primary_key=True)
    document = models.ForeignKey(Document)
    part = models.ForeignKey(Part, null=True)

    content = models.TextField()
    title = models.CharField(max_length=5000)

    # Which chapter is this, in order?
    ordinal = models.PositiveIntegerField(default=1)

    def render(self):
        f = StringIO(self.content)
        root = etree.parse(f)
        rendered = TEI_XSLT(root)
        return etree.tostring(rendered, encoding='utf-8', pretty_print=True, xml_declaration=False)

    def render_preview(self):
        f = StringIO(self.content)
        root = etree.parse(f)
        rendered = None
        preview = (root.xpath('(//tei:p)[1]', namespaces= {'tei': TEI }))[0]
        rendered = TEI_XSLT(preview)
        return etree.tostring(rendered, encoding='utf-8', pretty_print=True, xml_declaration=False)        
    
    @permalink
    def get_absolute_url(self):
        return ('threepress.search.views.document_chapter_view', [self.document.id, self.id])

    def link(self, text=None):
        if not text:
            text = self.title
        return '<a href="%s">%s</a>' % (self.get_absolute_url(), self.title)

    def __part_title__(self):
        if self.part:
            return self.part.title
        return ""

    def __unicode__(self):
        return "%s: %s %s (%d)" % (self.document.title, self.__part_title__(), self.title, self.ordinal)

    class Admin:
        pass

    class Meta:
        ordering = ['ordinal']


class Page(models.Model):
    name = models.CharField(max_length=5000)
    content = models.TextField()


class Result:
    highlighted_content = None
    def __init__(self, id, xapian_document):
        self.id = id
        self.document_id = xapian_document.get_value(settings.SEARCH_DOCUMENT_ID)
        self.xapian_document = xapian_document
        self.title = Chapter.objects.get(id=self.get_chapter_id()).title
    def get_chapter_id(self):
        return self.xapian_document.get_value(settings.SEARCH_CHAPTER_ID)
    def get_document_title(self):
        return self.xapian_document.get_value(settings.SEARCH_DOCUMENT_TITLE)
