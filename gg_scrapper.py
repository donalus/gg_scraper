#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
Download a Google Group to MBOX
Copyright (C) 2014 Matěj Cepl

This program is free software: you can redistribute it and/or modify it
under the terms of the GNU General Public License as published by the
Free Software Foundation, either version 3 of the License, or (at your
option) any later version.

This program is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
General Public License for more details.

You should have received a copy of the GNU General Public License along
with this program.  If not, see <http://www.gnu.org/licenses/>.'
"""
from __future__ import absolute_import, print_function, unicode_literals

import argparse
try:
    from configparser import ConfigParser
except ImportError:
    from ConfigParser import ConfigParser
import mailbox
import os.path
import re
import shutil
import subprocess
import sys
try:
    from urllib.error import HTTPError
    from urllib.request import HTTPHandler, HTTPRedirectHandler, \
        build_opener
except ImportError:
    from urllib2 import (HTTPError, HTTPHandler, HTTPRedirectHandler,
                         build_opener)
#from concurrent.futures import ProcessPoolExecutor
from bs4 import BeautifulSoup
import logging
logging.basicConfig(format='%(levelname)s:%(funcName)s:%(message)s',
                    level=logging.INFO)

ADDR_SEC_LABEL = 'addresses'
MANGLED_ADDR_RE = re.compile(
    r'([a-zA-Z0-9_.+-]+\.\.\.@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)',
    re.IGNORECASE)

__version__ = '0.4'


class Page(object):
    verb_handler = HTTPHandler()
    if logging.getLogger().getEffectiveLevel() == logging.DEBUG:
        verb_handler.set_http_debuglevel(2)
    redir_handler = HTTPRedirectHandler()
    opener = build_opener(verb_handler, redir_handler)

    def __init__(self):
        pass

    @staticmethod
    def unenscape_Google_bang_URL(old_URL):
        """
        See https://developers.google.com/webmasters\
                /ajax-crawling/docs/getting-started for more information
        """
        if old_URL.find('#!') != -1:
            esc_URL = old_URL.replace('#!', '?_escaped_fragment_=')
            return esc_URL
        else:
            return old_URL

    @classmethod
    def do_redirect(cls, URL):
        res = cls.opener.open(URL)

        if res.getcode() == 200:
            new_URL = res.geturl()
            return cls.unenscape_Google_bang_URL(new_URL)
        else:
            raise HTTPError('Unknown URL: {}'.format(URL))

    def _get_page_BS(self, URL):
        res = self.opener.open(self.do_redirect(URL))
        in_str = res.read()
        bs = BeautifulSoup(in_str)
        res.close()
        return bs


class Article(Page):
    def __init__(self, URL):
        super(Article, self).__init__()
        self.root = URL.replace('d/msg/', 'forum/message/raw?msg=')
        self.raw_message = ''

    def collect_message(self):
        logging.debug('self.root = {}'.format(self.root))
        try:
            res = self.opener.open(self.root)
            raw_msg = res.read()
            proc = subprocess.Popen(['/usr/bin/formail'],
                                    stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE,
                                    universal_newlines=True)
            result = proc.communicate(raw_msg.decode())[0]
        except HTTPError as exc:
            logging.warning('Exception on downloading {}:\n{}'.format(
                self.root, exc))
        finally:
            res.close()

        return result


class Topic(Page):
    def __init__(self, URL, name):
        super(Topic, self).__init__()
        self.name = name
        self.root = self.do_redirect(URL)
        self.articles = []

    def __unicode__(self):
        return "%s: %s" % (self.root, self.name)

    @staticmethod
    def get_one_article(elem):
        return elem

    def get_count_articles(self):
        '''Get total number of articles from the number on the page
        itself.
        '''
        BS = self._get_page_BS(self.root)
        i_elem = BS.find_all('i')
        if len(i_elem) <= 0:
            raise ValueError('Cannot find count of topics!')

        i_str = i_elem[0].string
        return int(re.match(r'\D+ \d+\D+\d+ \D+ (\d+) \D+$', i_str).group(1))

    def get_articles(self):
        out = []
        page = self._get_page_BS(self.root)
        for a_elem in page.find_all('a'):
            if 'href' in a_elem.attrs:
                a_href = a_elem['href']
                if re.match(r'https://groups.google.com/d/msg/',
                            a_href) is not None:
                    out.append(Article(a_href))

        return out


class Group(Page):
    def __init__(self, URL):
        super(Group, self).__init__()
        self.group_URL = URL
        self.topics = []
        match = re.match(r'https://groups.google.com/forum/#!forum/(.+)',
                         URL)
        if match is not None:
            self.name = match.group(1)

    @staticmethod
    def get_count_topics(BS):
        '''Get total number of topics from the number on the page
        itself.

        Which would be awesome for control, except it is wrong on all
        pages in various and different ways. :(
        '''
        i_elem = BS.find_all('i')
        if len(i_elem) <= 0:
            raise ValueError('Cannot find count of topics!')

        i_str = i_elem[0].string
        return int(re.match(r'\D+ \d+ - \d+ \D+ (\d+) \D+$', i_str).group(1))

    @staticmethod
    def get_one_topic(elem):
        sys.stdout.write('. ')
        sys.stdout.flush()
        if 'title' in elem.attrs:
            # filter out all-non-topic <a>s
            return True, Topic(elem['href'], elem['title'])
        else:
            logging.debug('other = %s', elem)
            return False, elem

    def get_topics(self):
        '''Recursively[?] get all topic (as special objects)
        Also return (for error checking) number of topics from the head
        of the topic page.
        '''
        out = []
        other = []
        BS = self._get_page_BS(self.group_URL)
        for a_elem in BS.find_all('a'):
            is_topic, res = self.get_one_topic(a_elem)
            if is_topic:
                out.append(res)
            else:
                other.append(res)

        if len(other) == 1:
            new_bs = Group(other[0]['href'])
            out.extend(new_bs.get_topics())
        elif len(other) != 0:
            raise ValueError(
                'There must be either one or none link to the next page!')

        sys.stdout.write('\n')
        sys.stdout.flush()
        return out

    def collect_group(self):
        self.topics = self.get_topics()
        len_topics = len(self.topics)
        for top in self.topics:
            print('[%d/%d] downloading "%s"' % (self.topics.index(top),
                  len_topics, top.name))
            arts = top.get_articles()
            top.articles = arts
            for a in arts:
                msg = a.collect_message()
                if msg is not None:
                    a.raw_message = msg

    def all_messages(self):
        '''Iterate over all messages in the group'''
        for top in self.topics:
            for art in top.articles:
                yield art.raw_message

    def collect_mangled_addrs(self):
        addrs = set()
        for top in self.topics:
            for art in top.articles:
                msg_str = art.raw_message
                # see http://stackoverflow.com/questions/201323
                msg_matches = MANGLED_ADDR_RE.findall(msg_str)
                if msg_matches is not None:
                    for mtch in msg_matches:
                        addrs.add(mtch)

        addrs = sorted(list(addrs))

        with open('{}.cnf'.format(self.name), 'w') as cnf_f:
            cnf_p = ConfigParser()
            cnf_p.add_section(ADDR_SEC_LABEL)
            for addr in addrs:
                cnf_p.set(ADDR_SEC_LABEL, addr, '')
            cnf_p.write(cnf_f)


class MBOX(mailbox.mbox):
    def __init__(self, filename):
        if os.path.exists(filename):
            shutil.move(filename, '{0}.bak'.format(filename))
        mailbox.mbox.__init__(self, filename)
        self.box_name = filename

    def write_group(self, group_object):
        self.lock()
        for mbx_str in group_object.all_messages():
            self.add(mbx_str.encode())
        self.unlock()
        self.close()


def main(group_URL):
    # Collect all messages to the internal variables
    grp = Group(group_URL)
    grp.collect_group()

    #import yaml
    # dump the state for debugging
    #with open('group.yaml', 'w') as yf:
    #    yaml.dump(grp, yf)

    # Write MBOX
    mbx = MBOX("{}.mbx".format(grp.name))
    mbx.write_group(grp)

    # generate list of addresses protected against spammers
    grp.collect_mangled_addrs()


def demangle(correct_list, orig_mbx, out_mbx):
    cnf_p = ConfigParser()
    cnf_p.read(correct_list)
    pairs = dict(cnf_p.items(ADDR_SEC_LABEL))

    if os.path.exists(out_mbx):
        shutil.move(out_mbx, '{}.bak'.format(out_mbx))

    in_mbx = mailbox.mbox(orig_mbx)
    out_mbx = mailbox.mbox(out_mbx)

    out_mbx.lock()
    for msg in in_mbx.itervalues():
        msg_str = str(msg)
        matches = MANGLED_ADDR_RE.search(msg_str)
        if matches is not None:
            u_from = msg.get_from()
            for orig, fixed in pairs.items():
                if (orig is not None) and (fixed is not None):
                    continue
                msg_str = msg_str.replace(orig, fixed)
            out_msg = mailbox.mboxMessage(msg_str)
            out_msg.set_from(u_from)

            out_mbx.add(out_msg)
        else:
            out_mbx.add(msg)
    out_mbx.close()
    in_mbx.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=
                                     'Scrape a Google Groups group.')
    parser.add_argument('group', metavar='URL', nargs='?',
                        help='URL of the group')
    parser.add_argument('-d', '--demangle', metavar='DEMANGLE_FILE', nargs=3,
                        help='Demangle mbox from stdin to stdout' +
                        'according to the values in the configuration' +
                        'file.')
    args = parser.parse_args()

    logging.debug('args = {}'.format(args))

    if args.demangle is not None:
        demangle(args.demangle[0], args.demangle[1], args.demangle[2])
    else:
        main(args.group)
