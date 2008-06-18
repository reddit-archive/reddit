# "The contents of this file are subject to the Common Public Attribution
# License Version 1.0. (the "License"); you may not use this file except in
# compliance with the License. You may obtain a copy of the License at
# http://code.reddit.com/LICENSE. The License is based on the Mozilla Public
# License Version 1.1, but Sections 14 and 15 have been added to cover use of
# software over a computer network and provide for limited attribution for the
# Original Developer. In addition, Exhibit A has been modified to be consistent
# with Exhibit B.
# 
# Software distributed under the License is distributed on an "AS IS" basis,
# WITHOUT WARRANTY OF ANY KIND, either express or implied. See the License for
# the specific language governing rights and limitations under the License.
# 
# The Original Code is Reddit.
# 
# The Original Developer is the Initial Developer.  The Initial Developer of the
# Original Code is CondeNet, Inc.
# 
# All portions of the code written by CondeNet are Copyright (c) 2006-2008
# CondeNet, Inc. All Rights Reserved.
################################################################################
from __future__ import with_statement
from distutils.cmd import Command
from distutils.errors import DistutilsOptionError

from pylons.i18n import _
from babel import Locale
import os, re
import cPickle as pickle
from wrapped import Wrapped
from utils import Storage
from md5 import md5

from logger import WithWriteLock, LoggedSlots

from datetime import datetime, timedelta
import time

try:
    import reddit_i18n
    _i18n_path = os.path.dirname(reddit_i18n.__file__)
except ImportError:
    _i18n_path = os.path.abspath('r2/i18n')

import pylons
from pylons.i18n.translation import translation, LanguageError, NullTranslations

def _get_translator(lang, graceful_fail = False, **kwargs):
    from pylons import config as conf
    """Utility method to get a valid translator object from a language name"""
    if not isinstance(lang, list):
        lang = [lang]
    try:
        translator = translation(conf['pylons.package'], _i18n_path, 
                                 languages=lang, **kwargs)
    except IOError, ioe:
        if graceful_fail:
            translator = NullTranslations()
        else:
            raise LanguageError('IOError: %s' % ioe)
    translator.pylons_lang = lang
    return translator


def set_lang(lang, graceful_fail = False, **kwargs):
    """Set the i18n language used"""
    registry = pylons.request.environ['paste.registry']
    if not lang:
        registry.replace(pylons.translator, NullTranslations())
    else:
        translator = _get_translator(lang, graceful_fail = graceful_fail, **kwargs)
        registry.replace(pylons.translator, translator)


comment = re.compile(r'^\s*#')
msgid = re.compile(r'^\s*msgid\s+"')
msgid_pl = re.compile(r'^\s*msgid_plural\s+"')
msgstr = re.compile(r'^\s*msgstr(\[\d\])?\s+"')
str_only = re.compile(r'^\s*"')

substr = re.compile("(%(\([^\)]+\))?([\d\.]+)?[a-zA-Z])")

source_line = re.compile(": (\S+\.[^\.]+):(\d+)")

from r2.config.templates import tpm

tpm.add('translator',       'html', file = "translation.html")



_domain = 'r2'

def hax(string):
    """when site translation strings change, this will allow the subsequent 
       language translations to be updated without giving the translator more
       work"""
    hax_dict = { }
    return hax_dict.get(string, string)
    

class TranslatedString(Wrapped):
    class _SubstString:
        def __init__(self, string, enabled = True):
            self.str = hax(string)
            subst = substr.findall(string)
            self.subst = set(x[0] for x in subst)
            self.name = set(x[1].strip(')').strip('(') for x in subst if x[1])

        def __str__(self):
            return self.str

        def unicode(self):
            if isinstance(self.str, unicode):
                return self.str
            return unicode(self.str, "utf-8")
        
        def __repr__(self):
            return self.str

        def _po_str(self, header, cut = 60):
            if len(self.str) > cut:
                if '\\n' in self.str:
                    txt = [i + "\\n" for i in self.str.split('\\n') if i]
                else:
                    txt = [self.str] #[self.str[i:i+cut]
                           #for i in range(0, len(self.str), cut)]
                res = '%s ""\n' % header
                for t in txt:
                    res += '"%s"\n' % t.replace('"', '\\"')
            else:
                res = '%s "%s"\n' % (header, self.str.replace('"', '\\"'))
            if isinstance(res, unicode):
                return res.encode('utf8')
            return res

        def highlight(self, func):
            res = self.str
            for x in self.subst:
                res = res.replace(x, func(x))
            return res

        def valid(self):
            try:
                # enforce validatation for named replacement rules only
                if self.name:
                    x = self.str % dict((k, 0) for k in self.name if k)
                return True
            except:
                return False

        def compatible(self, other):
            # compatibility implies every substitution rule in other
            # must be in self.
            return other.valid() and (not self.name or other.subst.issubset(self.subst))

    def __init__(self, translator, sing, plural = '', message = '',
                 enabled = True, locale = '', tip = ''):
        Wrapped.__init__(self, self)

        self.translator = translator
        self.message = message
        self.enabled = enabled
        self.locale = locale
        self.tip = ''

        # figure out where this item appears in the source
        source = source_line.findall(message)
        if source:
            self.source, self.line = source[0]
        else:
            self.source = self.line = ''

        self.msgid = self._SubstString(sing)
        self.msgid_plural = self._SubstString(plural)
        if str(self.msgid_plural):
            self.msgstr = []
        else:
            self.msgstr = self._SubstString('')

    @property
    def singular(self):
        return self.msgid.unicode() or ''

    def _singular(self, func):
        return self.msgid.highlight(func)

    @property
    def plural(self):
        return self.msgid_plural.unicode() or ''

    def _plural(self, func):
        return self.msgid_plural.highlight(func)

    def is_translated(self):
        if str(self.msgid_plural):
            return bool(self.msgstr) and any([x.str for x in self.msgstr])
        else:
            return bool(self.msgstr.str)


    def translation(self, indx = 0):
        if self.plural:
            if indx < len(self.msgstr):
                return self.msgstr[indx].unicode() or ''
            return ''
        else:
            return self.msgstr.unicode() or ''

    def add(self, translation, index = -1):
        new = self._SubstString(translation)
        if unicode(self.msgid_plural):
            if index >= 0:
                while index >= len(self.msgstr):
                    self.msgstr.append('')
                self.msgstr[index] = new
            else:
                self.msgstr.append(new)
        else:
            self.msgstr = new

    def __getitem__(self, indx):
        return self.translation(indx)

    def __setitem__(self, indx, value):
        return self.add(value, index = indx)

    @property
    def md5(self):
        return md5(unicode(self.singular) + unicode(self.plural)).hexdigest()

    def __repr__(self):
        return "<TranslatioString>"

    def __str__(self):
        res = ''
        if self.message:
            res = '#' + self.message.replace('\n', '\n#')
            if res[-1] == '#': res = res[:-1]
        res += self.msgid._po_str('msgid')
        if unicode(self.msgid_plural):
            res += self.msgid_plural._po_str('msgid_plural')
            for i in range(0, min(len(self.msgstr), self.translator.nplurals)):
                res += self.msgstr[i]._po_str('msgstr[%d]'%i)
        else:
            res += self.msgstr._po_str('msgstr')
        res += "\n"
        try:
            return str(res)
        except UnicodeEncodeError:
            return unicode(res + "\n").encode('utf-8')


    def is_valid(self, indx = -1):
        if self.plural:
            if indx < 0:
                return all(self.is_valid(i) for i in range(0,len(self.msgstr)))
            elif indx < len(self.msgstr):
                return self.msgid.compatible(self.msgstr[indx]) or \
                       self.msgstr.compatible(self.msgstr[indx])
            return True
        else:
            return self.msgid.compatible(self.msgstr)
            

class GettextHeader(TranslatedString):
    def __init__(self, translator, sing, plural = '', message = '',
                 enabled = True, locale = ''):
        TranslatedString.__init__(self, translator, '', '', message=message,
                                  enabled = False, locale = locale)
        self.headers = []

    def add(self, translation, index = -1):
        if index < 0:
            header_keys = set()
            self.msgstr = self._SubstString(translation)
            for line in translation.split('\\n'):
                line = line.split(':')
                header_keys.add(line[0])
                self.headers.append([line[0], ':'.join(line[1:])])
            # http://www.gnu.org/software/gettext/manual/gettext.html#Plural-forms
            if "Plural-Forms" not in header_keys:
                self.headers.append(["Plural-Forms",
                                     "nplurals=2; plural=(n != 1);"])
                
        elif self.headers and len(self.headers) > index:
            self.headers[index][1] = translation
            t = '\\n'.join('%s:%s' % tuple(h) for h in self.headers if h[0])
            self.msgstr = self._SubstString(t)
        
    def __repr__(self):
        return "<GettextHeader>"

class Translator(LoggedSlots):

    __slots__ = ['enabled', 'num_completed', 'num_total', 'author',
                 'nplurals', 'plural_names', 'source_trans', 'name', 
                 'en_name', '_is_enabled']

    def __init__(self, domain = _domain, path = _i18n_path,
                 locale = ''):
        self.strings = []
        self.string_dict = {}
        self.sources = {}

        self.locale = locale
        self.input_file = TranslatorTemplate.outfile(locale)

        def _out_file(extension = None):
            d = dict(extension=extension) if extension is not None else {}
            return self.outfile(locale, path=path, domain=domain, **d)
        self._out_file = _out_file

        # create directory for translation
        if not os.path.exists(os.path.dirname(self._out_file('po'))):
            os.makedirs(os.path.dirname(self._out_file('po')))

        LoggedSlots.__init__(self, self._out_file('data'), 
                             plural_names = ['singular', 'plural'],
                             nplurals = 2,
                             source_trans = {},
                             author = set([]),
                             enabled = {},
                             num_completed = 0,
                             num_total = 0,
                             en_name = locale,
                             name = locale,
                             _is_enabled = False
                             )

        # no translation, use the infile to make one
        if not os.path.exists(self._out_file('po')):
            self.from_file(self.input_file)
        # translation exists: make sure infile is not newer
        else:
            i_stat = os.stat(self.input_file)
            o_stat = os.stat(self._out_file('po'))
            if i_stat.st_mtime > o_stat.st_mtime:
                self.from_file(self.input_file)
                self.load_specialty_strings()
                self.from_file(self._out_file('po'), merge=True)
                self.save()
            else:
                self.from_file(self._out_file('po'))
                self.load_specialty_strings()


    def is_valid(self):
        for x in self.get_invalid():
            return False
        return True

    def get_invalid(self):
        for k, indx in self.string_dict.iteritems():
            if not self.strings[indx].is_valid():
                yield (k, self.strings[indx].singular)
    
    def from_file(self, file, merge = False):
        with open(file, 'r') as handle:
            line = True
            while line:
                line = handle.readline()
                msg = ''
                while comment.match(line):
                    msg += '#'.join(line.split('#')[1:])
                    line = handle.readline()
                if msgid.match(line):
                    txt_pl = ''
                    r, txt_sing, line = get_next_str_block(line, handle)
                    # grab plural if it exists
                    if msgid_pl.match(line):
                        r, txt_pl, line = get_next_str_block(line, handle)
                    if txt_sing or txt_pl:
                        ts = TranslatedString(self, txt_sing, txt_pl, 
                                          message = msg,
                                          locale = self.locale)
                    else:
                        ts = GettextHeader(self, txt_sing, txt_pl, 
                                           message = msg,
                                           locale = self.locale)
                    key = ts.md5
                    if self.enabled.has_key(key):
                        ts.enabled = self.enabled[key]
                    while msgstr.match(line):
                        r, translation, line = get_next_str_block(line, handle)
                        ts.add(translation)

                    if not merge and not self.string_dict.has_key(key):
                        self.string_dict[key] = len(self.strings)
                        self.strings.append(ts)
                        self.sources[md5(ts.source).hexdigest()] = ts.source
                    elif merge and self.string_dict.has_key(key):
                        i = self.string_dict[key]
                        self.strings[i].msgstr = ts.msgstr
                        self.sources[md5(ts.source).hexdigest()] = ts.source

    def load_specialty_strings(self):
        from r2.lib.strings import rand_strings
        for name, rs in rand_strings:
            for desc in rs:
                message = ": randomstring:%s\n" % name
                ts = TranslatedString(self, desc, "", message = message,
                                      locale = self.locale)
                key = ts.md5
                if not self.string_dict.has_key(key):
                    self.string_dict[key] = len(self.strings)
                    self.strings.append(ts)
                else:
                    ts = self.strings[self.string_dict[key]]
                self.sources[md5(ts.source).hexdigest()] = ts.source
                ts.enabled = True


    def __getitem__(self, key):
        return self.strings[self.string_dict[key]]

    def get(self, key, alt = None):
        indx = self.string_dict.get(key)
        if indx is not None:
            return self.strings[self.string_dict[key]]
        else:
            return alt

    def set(self, key, val, indx = -1):
        s = self.get(key)
        if s: s[indx] = val


    def to_file(self, file, compile=False, mo_file=None):
        with WithWriteLock(file) as handle:
            for string in self.strings:
                handle.write(str(string))
        if compile and self.is_valid():
            if mo_file:
                out_file = mo_file
            elif file.endswith(".po"):
                out_file = file[:-3] + ".mo"
            else:
                out_file = file + ".mo"
            
            cmd = 'msgfmt -o "%s" "%s"' % (out_file, file)
            with os.popen(cmd) as handle:
                x = handle.read()
            

    def __iter__(self):
        for x in self.strings:
            yield x

    def __repr__(self):
        return "<Translation>"

    @classmethod
    def outfile(cls, locale, domain = _domain, path = _i18n_path,
                extension = 'po'):
        return os.path.join(path, locale, 'LC_MESSAGES',
                            domain + '.' + extension)

    @classmethod
    def in_use(cls, locale, domain = _domain, path = _i18n_path):
        return os.path.exists(cls.outfile(locale, domain=domain, path=path,
                                          extension='mo'))


    @classmethod
    def exists(cls, locale, domain = _domain, path = _i18n_path):
        return os.path.exists(cls.outfile(locale, domain=domain, path=path))


    def save(self, compile = False):
        self.to_file(self._out_file('po'), compile = compile,
                     mo_file = self._out_file('mo'))
        self.gen_stats()
        self.dump_slots()

    def __repr__(self):
        return "<Translator>"


    @classmethod
    def get_slots(cls, locale = 'en'):
        f = cls.outfile(locale, extension='data')
        return LoggedSlots._get_slots(f)

    def load_slots(self):
        LoggedSlots.load_slots(self)
        # clobber enabled and translation using primary template
        if self.input_file != self._out_file():
            parent_slots = TranslatorTemplate.get_slots()
            self.enabled = parent_slots.get('enabled',{})
            self.source_trans = parent_slots.get('source_trans', {})
            
        #if self.enabled:
        #    for key, state in self.enabled.iteritems():
        #        self.set_enabled(key, state)

    def gen_stats(self):
        enabled = {}
        num_completed = 0
        num_strings = 0
        for h, indx in self.string_dict.iteritems():
            s = self.strings[indx]
            enabled[h] = s.enabled
            if s.enabled:
                num_strings +=1
                if s.is_translated():
                    num_completed += 1
        self.enabled = enabled
        self.num_completed = num_completed
        self.num_total = num_strings


    @classmethod
    def get_author(cls, locale):
        slots = cls.get_slots(locale)
        return slots.get("author", set([]))

    @classmethod
    def get_name(cls, locale):
        slots = cls.get_slots(locale)
        return slots.get("name", locale)

    @classmethod
    def get_en_name(cls, locale):
        slots = cls.get_slots(locale)
        return slots.get("en_name", locale)

    @classmethod
    def is_enabled(cls, locale):
        slots = cls.get_slots(locale)
        return slots.get("_is_enabled", False)

    @classmethod
    def get_complete_frac(cls, locale):
        infos = cls.get_slots(locale)
        comp = infos.get('num_completed', 0)
        tot = infos.get('num_total', 1)
        return float(comp)/float(tot)

    def set_enabled(self, key, state = True):
        indx = self.string_dict.get(key, None)
        if indx is not None:
            self.strings[indx].enabled = state
    
def list_translations(path = _i18n_path):
    trans = []
    for lang in  os.listdir(path):
        x = os.path.join(path, lang, 'LC_MESSAGES')
        if os.path.exists(x) and os.path.isdir(x):
            if Translator.exists(lang):
                trans.append(lang)
    return trans
        
class rebuild_translations(Command):
    user_options = []
    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self, path = _i18n_path):
        _rebuild_trans(path)

def _rebuild_trans(path = _i18n_path):
    for lang in os.listdir(path):
        x = os.path.join(path, lang, 'LC_MESSAGES')
        if os.path.exists(x) and os.path.isdir(x):
            if Translator.exists(lang):
                print "recompiling '%s'" % (lang)
                t = get_translator(lang)
                t.save(compile = True)


def _get_languages(path = _i18n_path):
    trans = []
    trans_name = {}
    for lang in os.listdir(path):
        x = os.path.join(path, lang, 'LC_MESSAGES')
        if os.path.exists(x) and os.path.isdir(x):
            name = Translator.get_name(lang)
            trans_name[lang] = name
            if Translator.is_enabled(lang) and Translator.in_use(lang):
                # en is treated specially
                if lang != 'en':
                    trans.append(lang)
                    if Translator.get_complete_frac(lang) < .5:
                        name += ' (*)'
    trans.sort()
    trans.insert(0, 'en')
    trans_name['en'] = "English"
    return trans, trans_name
    


class TranslatorTemplate(Translator):
    @classmethod
    def outfile(cls, locale, domain = _domain, path = _i18n_path,
                extension = 'pot'):
        return os.path.join(path, domain + '.' + extension)

    # defunct to_file since pot file is uneditable
    def to_file(*a, **kw):
        pass

    

class AutoTranslator(Translator):
    def __init__(self, **kw):
        Translator.__init__(self, **kw)
        for string in self.strings:
            if not string.is_translated():
                string.add(self.translate(string.singular), index = 0)
                if string.plural:
                    string.add(self.translate(string.plural), index = 1)
                    
    def translate(self, string):
        s = string.split("%")
        s, d = s[0], s[1:]
        substr = re.compile("((\([^\)]+\))?([\d\.]+)?[a-zA-Z])(.*)")
        def _sub(m):
            g =  m.groups()
            return "%s%s" % (g[0], self.trans_rules(g[-1]))

        d = [self.trans_rules(s)] + [substr.sub(_sub, x) for x in d]
        return '%'.join(d)
        
    def trans_rules(self, text):
        return text

class Transliterator(AutoTranslator):
    def __init__(self, **kw):
        Translator.__init__(self, **kw)
        for string in self.strings:
            if string.is_translated() \
                    and not isinstance(string, GettextHeader):
                if string.plural:
                    string.add(self.translate(string.msgstr[0].unicode()), 
                               index = 0)
                    string.add(self.translate(string.msgstr[1].unicode()), 
                               index = 1)
                else:
                    string.add(self.translate(string.msgstr.unicode()), 
                               index = 0)
    

class USEnglishTranslator(AutoTranslator):
    def trans_rules(self, string):
        return string
        

class TamilTranslator(Transliterator):
    transliterator = dict([(u'a', u'\u0b85'),
                           (u'A', u'\u0b86'),
                           (u'i', u'\u0b87'),
                           (u'I', u'\u0b88'),
                           (u'u', u'\u0b89'),
                           (u'U', u'\u0b8a'),
                           (u'e', u'\u0b8e'),
                           (u'E', u'\u0b8f'),
                           (u'o', u'\u0b92'),
                           (u'O', u'\u0b93'),

                           (u'g', u'\u0b95\u0bcd'),
                           (u'c', u'\u0b95\u0bcd'),
                           (u'k', u'\u0b95\u0bcd'),
                           (u'q', u'\u0b95\u0bcd'),
                           (u'G', u'\u0b95\u0bcd'),
                           (u'K', u'\u0b95\u0bcd'),

                           (u's', u'\u0b9a\u0bcd'),
                           (u'C', u'\u0b9a\u0bcd'),

                           (u't', u'\u0b9f\u0bcd'),
                           (u'D', u'\u0b9f\u0bcd'),
                           (u'T', u'\u0b9f\u0bcd'),
                           (u'N', u'\u0ba3\u0bcd'),
                           (u'd', u'\u0ba4\u0bcd'),
                           (u'$', u'\u0ba8\u0bcd'), 
                           (u'n', u'\u0ba9\u0bcd'),
                           (u'B', u'\u0baa\u0bcd'),
                           (u'b', u'\u0baa\u0bcd'),
                           (u'f', u'\u0baa\u0bcd'),
                           (u'p', u'\u0baa\u0bcd'),
                           (u'F', u'\u0baa\u0bcd'),
                           (u'P', u'\u0baa\u0bcd'),
                           (u'm', u'\u0bae\u0bcd'),
                           (u'M', u'\u0bae\u0bcd'),
                           (u'y', u'\u0baf\u0bcd'),
                           (u'r', u'\u0bb0\u0bcd'),
                           (u'R', u'\u0bb1\u0bcd'),
                           (u'l', u'\u0bb2\u0bcd'),
                           (u'L', u'\u0bb3\u0bcd'),
                           (u'Z', u'\u0bb4\u0bcd'),
                           (u'z', u'\u0bb4\u0bcd'),
                           (u'v', u'\u0bb5\u0bcd'),
                           (u'w', u'\u0bb5\u0bcd'),
                           (u'V', u'\u0bb5\u0bcd'),
                           (u'W', u'\u0bb5\u0bcd'),

                           (u'Q', u'\u0b83'),

                           (u'h', u'\u0bb9\u0bcd'),
                           (u'j', u'\u0b9c\u0bcd'),
                           (u'J', u'\u0b9c\u0bcd'),
                           (u'S', u'\u0bb8\u0bcd'),
                           (u'H', u'\u0bb9\u0bcd'),

                           (u'Y', u'\u0b20\u0bcd'),
                           (u'^', u'\u0b20')])

    ligatures = ((u'\u0ba9\u0bcd\u0b95\u0bcd', u'\u0B99\u0BCD'), # ng
                 (u'\u0ba9\u0bcd\u0b9c\u0bcd', u'\u0B9e\u0BCD'), # nj
                 (u'\u0b95\u0bcd\u0bb9\u0bcd', u'\u0b9a\u0bcd'), # ch -> C
                 (u'\u0b9f\u0bcd\u0bb9\u0bcd', u'\u0ba4\u0bcd'), # th -> d
                 (u'\u0ba4\u0bcd\u0bb9\u0bcd', u'\u0ba4\u0bcd'), # dh -> d

                 (u'\u0b85\u0b85', u'\u0b86'), # aa -> A
                 (u'\u0b85\u0b87', u'\u0b90'), # ai
                 (u'\u0b85\u0b89', u'\u0b94'), # au
                 (u'\u0b87\u0b87', u'\u0b88'), # ii -> I
                 (u'\u0b89\u0b89', u'\u0b8a'), # uu -> U
                 (u'\u0b8e\u0b8e', u'\u0b8f'), # ee -> E
                 (u'\u0b92\u0b92', u'\u0b93'), # oo -> O
                 # remove accent from consonants and convert to ligature
                 # based on the subsequent vowell
                 (u'\u0bcd\u0b85', u''),
                 (u'\u0bcd\u0b86', u'\u0bbe'),
                 (u'\u0bcd\u0b87', u'\u0bbf'),
                 (u'\u0bcd\u0b88', u'\u0bc0'),
                 (u'\u0bcd\u0b89', u'\u0bc1'),
                 (u'\u0bcd\u0b8a', u'\u0bc2'),
                 (u'\u0bcd\u0b8e', u'\u0bc6'),
                 (u'\u0bcd\u0b8f', u'\u0bc7'),
                 (u'\u0bcd\u0b90', u'\u0bc8'),
                 (u'\u0bcd\u0b92', u'\u0bca'),
                 (u'\u0bcd\u0b93', u'\u0bcb'),
                 (u'\u0bcd\u0b94', u'\u0bcc'),
                 )
    
    def trans_rules(self, string):
        t = u''.join(self.transliterator.get(x, x) for x in string)
        for k, v in self.ligatures:
            t = t.replace(k, v)
        return t
            

                          

import random
class LeetTranslator(AutoTranslator):
    def trans_rules(self, string):
        key = dict(a=["4","@"], 
                   b=["8"], c=["("],
                   d=[")", "|)"], e=["3"], 
                   f=["ph"], g=["6"], 
                   i=["1", "!"], j=["_/"], 
                   k=["X"], l=["1"], o=["0"], 
                   q=["0_"], s=["5", "$"], t=["7"], 
                   z=["2"])
        s = string.lower()
        s = (random.choice(key.get(x, [x])) for x in s)
        return ''.join(s)

def get_translator(locale):
    if locale == 'leet':
        return LeetTranslator(locale = locale)
    elif locale == 'en':
        return USEnglishTranslator(locale = locale)
    elif locale == 'ta':
        return TamilTranslator(locale = locale)
    return Translator(locale = locale)
    
def get_next_str_block(line, handle):
    res = ''
    before, middle, after = qnd_parse(line)
    txt = [middle]
    res += line
    line = handle.readline()
    # grab multi-line strings for this element
    while True:
        if not str_only.match(line): break
        res += line
        b, m, a = qnd_parse(line)
        txt.append(m)
        line = handle.readline()
    return res, (''.join(txt)).replace('\\"', '"'), line


def qnd_parse(line):
    p = line.split('#')
    after = '#'.join(p[1:])
    if after: after = "#" + after
    s = p[0].split('"')
    after = s[-1] + after
    before = s[0]
    middle = '"'.join(s[1:-1])
    return before, middle,  after

