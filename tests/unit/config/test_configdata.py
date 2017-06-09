# vim: ft=python fileencoding=utf-8 sts=4 sw=4 et:
# Copyright 2015-2017 Florian Bruhin (The Compiler) <mail@qutebrowser.org>

# This file is part of qutebrowser.
#
# qutebrowser is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# qutebrowser is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with qutebrowser.  If not, see <http://www.gnu.org/licenses/>.

"""Tests for qutebrowser.config.configdata."""

import textwrap

import yaml
import pytest

from qutebrowser.config import configdata, configtypes
from qutebrowser.utils import usertypes


# @pytest.mark.parametrize('sect', configdata.DATA.keys())
# def test_section_desc(sect):
#     """Make sure every section has a description."""
#     desc = configdata.SECTION_DESC[sect]
#     assert isinstance(desc, str)


# def test_data():
#     """Some simple sanity tests on data()."""
#     data = configdata.data()
#     assert 'general' in data
#     assert 'ignore-case' in data['general']


# def test_readonly_data():
#     """Make sure DATA is readonly."""
#     with pytest.raises(ValueError, match="Trying to modify a read-only "
#                                          "config!"):
#         configdata.DATA['general'].setv('temp', 'ignore-case', 'true', 'true')


def test_read_yaml_valid(tmpdir):
    filename = tmpdir / 'data.yml'
    filename.write(textwrap.dedent("""
        test1:
            type: Bool
            default: true
            desc: Hello World

        test2:
            type: String
            default: foo
            desc: Hello World 2
    """))
    data = configdata.read_yaml(str(filename))
    assert data.keys() == {'test1', 'test2'}
    assert data['test2'].default == "foo"
    assert data['test1'].description == "Hello World"
    # FIXME
    # assert isinstance(data['test1'].typ, configtypes.Bool)


def test_read_yaml_invalid_keys(tmpdir):
    filename = tmpdir / 'data.yml'
    filename.write(textwrap.dedent("""
        test:
            type: Bool
    """))
    with pytest.raises(ValueError, match='Invalid keys'):
        configdata.read_yaml(str(filename))


class TestParseYamlType:

    def _yaml(self, s):
        """Get the type from parsed YAML data."""
        return yaml.load(textwrap.dedent(s))['type']

    def test_simple(self):
        """Test type which is only a name."""
        data = self._yaml("type: Bool")
        typ = configdata._parse_yaml_type('test', data)
        assert isinstance(typ, configtypes.Bool)
        assert not typ.none_ok

    def test_complex(self):
        """Test type parsing with arguments."""
        data = self._yaml("""
            type:
              name: String
              minlen: 2
        """)
        typ = configdata._parse_yaml_type('test', data)
        assert isinstance(typ, configtypes.String)
        assert not typ.none_ok
        assert typ.minlen == 2

    def test_list(self):
        """Test type parsing with a list and subtypes."""
        data = self._yaml("""
            type:
              name: List
              elemtype: String
        """)
        typ = configdata._parse_yaml_type('test', data)
        assert isinstance(typ, configtypes.List)
        assert isinstance(typ.elemtype, configtypes.String)
        assert not typ.none_ok
        assert not typ.elemtype.none_ok

    def test_dict(self):
        """Test type parsing with a dict and subtypes."""
        data = self._yaml("""
            type:
              name: Dict
              keytype: String
              valtype:
                name: Int
                minval: 10
        """)
        typ = configdata._parse_yaml_type('test', data)
        assert isinstance(typ, configtypes.Dict)
        assert isinstance(typ.keytype, configtypes.String)
        assert isinstance(typ.valtype, configtypes.Int)
        assert not typ.none_ok
        assert typ.valtype.minval == 10


class TestParseYamlBackend:

    def _yaml(self, s):
        """Get the type from parsed YAML data."""
        return yaml.load(textwrap.dedent(s))['backend']

    @pytest.mark.parametrize('backend, expected', [
        ('QtWebKit', [usertypes.Backend.QtWebKit]),
        ('QtWebEngine', [usertypes.Backend.QtWebEngine]),
        # This is also what _parse_yaml_backends gets when backend: is not given
        # at all
        ('null', [usertypes.Backend.QtWebKit, usertypes.Backend.QtWebEngine]),
    ])
    def test_simple(self, backend, expected):
        """Check a simple "backend: QtWebKit"."""
        data = self._yaml("backend: {}".format(backend))
        backends = configdata._parse_yaml_backends('test', data)
        assert backends == expected

    @pytest.mark.parametrize('webkit, has_new_version, expected', [
        (True, True, [usertypes.Backend.QtWebKit,
                      usertypes.Backend.QtWebEngine]),
        (False, True, [usertypes.Backend.QtWebEngine]),
        (True, False, [usertypes.Backend.QtWebKit]),
    ])
    def test_dict(self, monkeypatch, webkit, has_new_version, expected):
        data = self._yaml("""
            backend:
              QtWebKit: {}
              QtWebEngine: Qt 5.8
        """.format('true' if webkit else 'false'))
        monkeypatch.setattr(configdata.qtutils, 'version_check',
                            lambda v: has_new_version)
        backends = configdata._parse_yaml_backends('test', data)
        assert backends == expected
