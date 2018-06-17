import xmlrpc.client
import base64
import zlib
import srt
from bs4 import UnicodeDammit
import textwrap
import itertools
from datetime import timedelta

COLUMN_WIDTH = 40


class Opensubtitles:
    ''' opensuntitles.org access'''

    user_agent = "TemporaryUserAgen"

    def __init__(self):
        '''Init xml-rpc proxy'''

        self.proxy = xmlrpc.client.ServerProxy(
                "https://api.opensubtitles.org/xml-rpc")

    def logout(self):
        ''' Logout from api.opensubtitles.org.'''

        try:
            self.proxy.LogOut(self.token)
        except xmlrpc.client.ProtocolError as err:
            print("Opensubtitles API protocol error: {0}".format(err))

    def login(self):
        ''' Login into api.opensubtitles.org.'''

        try:
            login = self.proxy.LogIn("", "", "en", "TemporaryUserAgent")
        except xmlrpc.client.ProtocolError as err:
            print("Opensubtitles API protocol error: {0}".format(err))
        else:
            self.token = login['token']

    def _select_sub_(self, subtitles):
        ''' Select subtitles that have maximal downloads count'''
        rate = 0
        top_sub = None

        for sub in subtitles:
            if int(sub['SubDownloadsCnt']) >= rate:
                rate = int(sub['SubDownloadsCnt'])
                top_sub = sub
        return top_sub

    def _save_sub_(self, name, data):
        with open(name, 'w') as f:
            f.write(data)

    def _save_sub_bin_(self, name, data):
        with open(name, 'wb') as f:
            f.write(data)

    def search_sub(self, imdbid, lang):
        '''
        Search the subtitles in Opensubtitles database
        by IMBD id and a language.
        Return dict as described in
        http://trac.opensubtitles.org/projects/opensubtitles/wiki/XMLRPC#SearchSubtitles
        Args:
            imdbid (int): Movie's IMDB id
            lang (str): Language of subtitles in ISO639 format
        Returns:
            sub (dict): subtitle in Opensubtitles API format
        '''
        try:
            result = self.proxy.SearchSubtitles(
                    self.token,
                    [{'imdbid': str(imdbid), 'sublanguageid': lang}],
                    [100])
        except xmlrpc.client.ProtocolError as err:
            print("Opensubtitles API protocol error: {0}".format(err))
        else:

            return self._select_sub_(result['data'])

    def download_sub(self, sub, save=True, save_orig=True, encoding=None):
        '''
        Download subtitles from subtitles.org.
        Return subtitles file as a bytearray
        '''
        try:
            result = self.proxy.DownloadSubtitles(self.token,
                                                  [sub['IDSubtitleFile']])
        except xmlrpc.client.ProtocolError as err:
            print("Opensubtitles API protocol error: {0}".format(err))
        else:
            data_zipped = base64.b64decode(result['data'][0]['data'])
            data_bytes = zlib.decompress(data_zipped, 15+32)
            return data_bytes


class Subs:

    def __init__(self, sub_b, encoding=None,
                 lang=None, movie_name=None, imdbid=None):
        self.lang = lang if lang else ""
        self.movie_name = movie_name if movie_name else ""
        self.imdbid = imdbid if imdbid else ""
        self.encoding = encoding
        self.sub_b = sub_b

        # Decode bytearray to Unicode string
        if self.encoding:
            data = sub_b.decode(self.encoding)
        else:
            data = UnicodeDammit(sub_b).unicode_markup

        self.sub = list(srt.parse(data))
        self._fix_subtitles_()

    def __repr__(self):
        return "Subs: [{}] [{}] [{}]".format(self.movie_name,
                                             self.imdbid,
                                             self.lang)

    def save(self, name=None):
        if name:
            file_name = name
        else:
            file_name = '_'.join([self.movie_name, self.imdbid, self.lang])
            file_name = file_name.replace(' ', '_')
            file_name = file_name.replace('"', '')
            file_name += '.srt'

        if self.encoding:
            data = self.sub_b.decode(self.encoding)
            with open(file_name, 'w') as f:
                f.write(data)
        else:
            with open(file_name, 'wb') as f:
                f.write(self.sub_b)

    @classmethod
    def read(cls, name, encoding=None,
             lang=None, movie_name=None, imdbid=None):

        subs_args = {'encoding': encoding, 'lang': lang,
                     'movie_name': movie_name, 'imdbid': imdbid}
        with open(name, 'rb') as f:
            data = f.read()

        return cls(data, **subs_args)

    def _fix_subtitles_(self):
        t = timedelta(seconds=0)
        i = 0
        for s in self.sub:
            if s.start < t:
                self.sub.pop(i)
                # print("removed: {}-{}".format(s.start, s.content))
            else:
                t = s.end
            i += 1

    def get_lines(self, start, length):
        '''
        Return list of <str> from subtitles
        whose timedelta are between start and stop.
        Args:
            start (float): 0-100 - start time of subtitles
                                   (percent of total length)
            length (int):  duration in seconds
        '''
        lines = []
        start_td = self.sub[-1].end * start/100 + self.offset
        end_td = start_td + timedelta(seconds=length)
        for line in self.sub:
            if line.start >= start_td and line.end <= end_td:
                lines.append(line.content)
            if line.start > end_td:
                return lines
        return lines

    def set_offset(self, sec):
        '''
        Args:
            sec (int): offset in seconds
        '''
        self.offset = timedelta(seconds=sec)

    def set_encoding(self, encoding):
        self.encoding = encoding
        data = self.sub_b.decode(self.encoding)
        self.sub = list(srt.parse(data))
        self._fix_subtitles_()


class SubPair:
    ''' Pair of subtitles'''

    def __init__(self, subs):
        '''
        Args:
            subs: list of <Subs> objects
        '''
        self.subs = subs
        self.subs[0].offset = timedelta(seconds=0)
        self.subs[1].offset = timedelta(seconds=0)

    @classmethod
    def download(cls, imdbid, lang1, lang2, enc1=None, enc2=None):
        osub = Opensubtitles()
        osub.login()

        subs = []
        for lang, enc in [(lang1, enc1), (lang2, enc2)]:
            sub = osub.search_sub(imdbid, lang)
            if sub:
                sub_args = {'lang': lang}
                sub_args['movie_name'] = sub['MovieName']
                sub_args['imdbid'] = sub['IDMovieImdb']
                sub_args['lang'] = sub['SubLanguageID']

                print("Downloading {} ...".format(lang))
                sub_b = osub.download_sub(sub)
                s = Subs(sub_b, **sub_args)
                subs.append(s)
            else:
                print("Subtitles #{} isn't found".format(imdbid))
                osub.logout()
                return None

        osub.logout()
        return cls(subs)

    def print_pair(self, offset=0, count=1):

        data = []
        for s in self.subs:
            lines = s.get_lines(offset, count)
            line = '\n'.join(lines)
            res = []
            for l in line.splitlines():
                res += textwrap.wrap(l, COLUMN_WIDTH)

            data.append(res)

        out = itertools.zip_longest(*data,  fillvalue="")

        for s in out:
            print("{}  |  {}".format(s[0]+(COLUMN_WIDTH-len(s[0]))*" ", s[1]))


if __name__ == '__main__':

    import sys
    sub_id = int(sys.argv[1])
    p = SubPair.download(sub_id, 'rus', 'eng')
    p.print_pair(20, 20)
    p.subs[0].set_encoding('cp1251')
    #`import ipdb; ipdb.set_trace()
    p.print_pair(20, 20)
    # sub_e = Subs.read("avengers_orig_en.srt")
    # sub_r = Subs.read("avengers_orig_ru.srt")

    # pp = SubPair([sub_r, sub_e])
    # pp.print_pair(offset, count)
