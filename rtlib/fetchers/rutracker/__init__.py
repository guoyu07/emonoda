#####
#
#    rtfetch -- Update rtorrent files from popular trackers
#    Copyright (C) 2012  Devaev Maxim <mdevaev@gmail.com>
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
#####


import urllib.parse
import http.cookiejar
import re

from ...core import fetcher


# =====
def _encode(arg):
    return arg.encode("cp1251")


def _decode(arg):
    return arg.decode("cp1251")


class Fetcher(fetcher.BaseFetcher, fetcher.WithLogin, fetcher.WithCaptcha, fetcher.WithOpener):
    def __init__(self, **kwargs):  # pylint: disable=super-init-not-called
        for parent in self.__class__.__bases__:
            parent.__init__(self, **kwargs)

        self._comment_regexp = re.compile(r"http://rutracker\.org/forum/viewtopic\.php\?t=(\d+)")

        self._cap_static_regexp = re.compile(r"\"(http://static\.rutracker\.org/captcha/[^\"]+)\"")
        self._cap_sid_regexp = re.compile(r"name=\"cap_sid\" value=\"([a-zA-Z0-9]+)\"")
        self._cap_code_regexp = re.compile(r"name=\"(cap_code_[a-zA-Z0-9]+)\"")

        self._hash_regexp = re.compile(r"<span id=\"tor-hash\">([a-zA-Z0-9]+)</span>")

        self._retry_codes = (503, 404)

    @classmethod
    def get_name(cls):
        return "rutracker"

    @classmethod
    def get_version(cls):
        return 1

    @classmethod
    def get_options(cls):
        params = {}
        for parent in cls.__bases__:
            params.update(parent.get_options())
        return params

    def test_site(self):
        opener = fetcher.build_opener(proxy_url=self._proxy_url)
        data = self._read_url("http://rutracker.org", opener=opener)
        self._assert_site(
            b"<link rel=\"shortcut icon\" href=\"http://static.rutracker.org"
            b"/favicon.ico\" type=\"image/x-icon\">" in data
        )

    def is_matched_for(self, torrent):
        return (self._comment_regexp.match(torrent.get_comment() or "") is not None)

    def is_torrent_changed(self, torrent):
        self._assert_match(torrent)
        return (torrent.get_hash() != self._fetch_hash(torrent))

    def fetch_new_data(self, torrent):
        self._assert_match(torrent)
        comment_match = self._comment_regexp.match(torrent.get_comment() or "")
        topic_id = comment_match.group(1)

        cookie = http.cookiejar.Cookie(
            version=0,
            name="bb_dl",
            value=topic_id,
            port=None,
            port_specified=False,
            domain="",
            domain_specified=False,
            domain_initial_dot=False,
            path="/forum/",
            path_specified=True,
            secure=False,
            expires=None,
            discard=True,
            comment=None,
            comment_url=None,
            rest={"HttpOnly": None},
            rfc2109=False,
        )
        self._cookie_jar.set_cookie(cookie)

        data = self._read_url(
            url="http://dl.rutracker.org/forum/dl.php?t={}".format(topic_id),
            data=b"",
            headers={
                "Referer": "http://rutracker.org/forum/viewtopic.php?t={}".format(topic_id),
                "Origin":  "http://rutracker.org",
            }
        )
        self._assert_valid_data(data)
        return data

    # ===

    def login(self):
        self._assert_auth(self._user is not None, "Required user for rutracker")
        self._assert_auth(self._passwd is not None, "Required passwd for rutracker")
        with self._make_opener():
            post = {
                "login_username": _encode(self._user),
                "login_password": _encode(self._passwd),
                "login":          b"\xc2\xf5\xee\xe4",
            }
            text = self._read_login(post)

            cap_static_match = self._cap_static_regexp.search(text)
            if cap_static_match is not None:
                cap_sid_match = self._cap_sid_regexp.search(text)
                cap_code_match = self._cap_code_regexp.search(text)
                self._assert_auth(cap_sid_match is not None, "Unknown cap_sid")
                self._assert_auth(cap_code_match is not None, "Unknown cap_code")

                post[cap_code_match.group(1)] = self._decode_captcha(cap_static_match.group(1))
                post["cap_sid"] = cap_sid_match.group(1)
                text = self._read_login(post)
                self._assert_auth(self._cap_static_regexp.search(text) is None, "Invalid captcha or password")

    def is_logged_in(self):
        return (self._opener is not None)

    # ===

    def _read_login(self, post):
        return _decode(self._read_url(
            url="http://login.rutracker.org/forum/login.php",
            data=_encode(urllib.parse.urlencode(post)),
        ))

    def _fetch_hash(self, torrent):
        text = _decode(self._read_url(torrent.get_comment()))
        hash_match = self._hash_regexp.search(text)
        self._assert_logic(hash_match is not None, "Hash not found")
        return hash_match.group(1).lower()