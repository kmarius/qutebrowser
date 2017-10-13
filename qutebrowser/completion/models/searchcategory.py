# vim: ft=python fileencoding=utf-8 sts=4 sw=4 et:

# Copyright 2017 Ryan Roden-Corrent (rcorre) <ryan@rcorre.net>
#
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

"""Completion category that uses a list of tuples as a data source."""

from PyQt5.QtCore import Qt, QSortFilterProxyModel, QUrl
from PyQt5.QtGui import QStandardItem, QStandardItemModel

from qutebrowser.utils import urlutils
from qutebrowser.config import config


class SearchCategory(QSortFilterProxyModel):

    """Expose a list of items as a category for the CompletionModel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.name = "Search"
        self.srcmodel = QStandardItemModel(parent=self)
        self.setSourceModel(self.srcmodel)
        self.columns_to_filter = [0]
        self.setFilterKeyColumn(-1)

    def set_pattern(self, val):
        """Setter for pattern.

        Args:
            val: The value to set.
        """
        self.srcmodel.clear()

        if not val:
            return

        engine, term = urlutils._parse_search_term(val)
        if engine is not None:
            template = config.val.url.searchengines[engine]
            tokens = template.split('|')
            if len(tokens) > 1:
                template = tokens[1]
                name = tokens[0]
            else:
                name = QUrl(template).host()
            self.srcmodel.appendRow([QStandardItem(template.format(term)),
                                     QStandardItem(name)])
