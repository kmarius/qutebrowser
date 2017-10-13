# vim: ft=python fileencoding=utf-8 sts=4 sw=4 et:

# Copyright 2014-2018 Florian Bruhin (The Compiler) <mail@qutebrowser.org>
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

"""The main browser widget for QtWebEngine."""

import functools

from PyQt5.QtCore import pyqtSignal, pyqtSlot, QUrl, PYQT_VERSION
from PyQt5.QtGui import QPalette
from PyQt5.QtWebEngineWidgets import (QWebEngineView, QWebEnginePage,
                                      QWebEngineScript,
                                      QWebEngineContextMenuData)
from PyQt5.QtWidgets import QAction, QMenu

from qutebrowser.browser import shared
from qutebrowser.browser.webengine import certificateerror, webenginesettings
from qutebrowser.config import config
from qutebrowser.utils import log, debug, usertypes, jinja, objreg, qtutils


class WebEngineView(QWebEngineView):

    """Custom QWebEngineView subclass with qutebrowser-specific features."""

    def __init__(self, *, tabdata, win_id, private, parent=None):
        super().__init__(parent)
        self._win_id = win_id
        self._tabdata = tabdata

        theme_color = self.style().standardPalette().color(QPalette.Base)
        if private:
            profile = webenginesettings.private_profile
            assert profile.isOffTheRecord()
        else:
            profile = webenginesettings.default_profile
        page = WebEnginePage(theme_color=theme_color, profile=profile,
                             parent=self)
        self.setPage(page)

    def shutdown(self):
        self.page().shutdown()

    def createWindow(self, wintype):
        """Called by Qt when a page wants to create a new window.

        This function is called from the createWindow() method of the
        associated QWebEnginePage, each time the page wants to create a new
        window of the given type. This might be the result, for example, of a
        JavaScript request to open a document in a new window.

        Args:
            wintype: This enum describes the types of window that can be
                     created by the createWindow() function.

                     QWebEnginePage::WebBrowserWindow:
                         A complete web browser window.
                     QWebEnginePage::WebBrowserTab:
                         A web browser tab.
                     QWebEnginePage::WebDialog:
                         A window without decoration.
                     QWebEnginePage::WebBrowserBackgroundTab:
                         A web browser tab without hiding the current visible
                         WebEngineView.

        Return:
            The new QWebEngineView object.
        """
        debug_type = debug.qenum_key(QWebEnginePage, wintype)
        background = config.val.tabs.background

        log.webview.debug("createWindow with type {}, background {}".format(
            debug_type, background))

        if wintype == QWebEnginePage.WebBrowserWindow:
            # Shift-Alt-Click
            target = usertypes.ClickTarget.window
        elif wintype == QWebEnginePage.WebDialog:
            log.webview.warning("{} requested, but we don't support "
                                "that!".format(debug_type))
            target = usertypes.ClickTarget.tab
        elif wintype == QWebEnginePage.WebBrowserTab:
            # Middle-click / Ctrl-Click with Shift
            # FIXME:qtwebengine this also affects target=_blank links...
            if background:
                target = usertypes.ClickTarget.tab
            else:
                target = usertypes.ClickTarget.tab_bg
        elif wintype == QWebEnginePage.WebBrowserBackgroundTab:
            # Middle-click / Ctrl-Click
            if background:
                target = usertypes.ClickTarget.tab_bg
            else:
                target = usertypes.ClickTarget.tab
        else:
            raise ValueError("Invalid wintype {}".format(debug_type))

        tab = shared.get_tab(self._win_id, target)
        return tab._widget  # pylint: disable=protected-access

    def contextMenuEvent(self, event):
        """We override this to get the (overridden) standard context menu from
        the page.
        """
        menu = self.page().createStandardContextMenu()
        menu.popup(event.globalPos())


class WebEnginePage(QWebEnginePage):

    """Custom QWebEnginePage subclass with qutebrowser-specific features.

    Attributes:
        _is_shutting_down: Whether the page is currently shutting down.
        _theme_color: The theme background color.

    Signals:
        certificate_error: Emitted on certificate errors.
        shutting_down: Emitted when the page is shutting down.
        navigation_request: Emitted on acceptNavigationRequest.
    """

    certificate_error = pyqtSignal()
    shutting_down = pyqtSignal()
    navigation_request = pyqtSignal(usertypes.NavigationRequest)

    def __init__(self, *, theme_color, profile, parent=None):
        super().__init__(profile, parent)
        self._is_shutting_down = False
        self.featurePermissionRequested.connect(
            self._on_feature_permission_requested)
        self._theme_color = theme_color
        self._set_bg_color()
        config.instance.changed.connect(self._set_bg_color)
        self.urlChanged.connect(self._inject_userjs)

    def createStandardContextMenu(self):
        data = self.contextMenuData()
        if not data:
            return None
        menu = QMenu(self.parent())

        # if data.isEditable() and !data.spellCheckerSuggestions().isEmpty()
        #     QPointer<QWebEnginePage> thisRef(this);
        #     for (int i=0; i < contextMenuData.spellCheckerSuggestions().count() && i < 4; i++) {
        #         QAction *action = new QAction(menu);
        #         QString replacement = contextMenuData.spellCheckerSuggestions().at(i);
        #         QObject::connect(action, &QAction::triggered, [thisRef, replacement] { if (thisRef) thisRef->replaceMisspelledWord(replacement); });
        #         action->setText(replacement);
        #         menu->addAction(action);
        #     }
        #     menu->addSeparator();
        # }

        if data.linkText() and data.linkUrl().isValid():
            action = self.action(QWebEnginePage.OpenLinkInThisWindow)
            action.setText("Follow Link")
            menu.addAction(action)
            menu.addAction(self.action(QWebEnginePage.DownloadLinkToDisk))

        if not data.selectedText():
            action = QAction("Back", menu)
            action.triggered.connect(self.parent().back)
            # action->setEnabled(d->adapter->canGoBack());
            menu.addAction(action)

            action = QAction("Forward", menu)
            action.triggered.connect(self.parent().forward)
            # action->setEnabled(d->adapter->canGoForward());
            menu.addAction(action)

            action = QAction("Reload", menu);
            action.triggered.connect(self.parent().reload)
            menu.addAction(action)

            menu.addAction(self.action(QWebEnginePage.ViewSource))
        else:
            menu.addAction(self.action(QWebEnginePage.Copy))
            menu.addAction(self.action(QWebEnginePage.Unselect))

        if data.linkText() and data.linkUrl().isValid():
            menu.addAction(self.action(QWebEnginePage.CopyLinkToClipboard))

        if data.mediaUrl().isValid():
            media_type = data.mediaType()
            if media_type == QWebEngineContextMenuData.MediaTypeImage:
                menu.addAction(self.action(QWebEnginePage.DownloadImageToDisk))
                menu.addAction(self.action(QWebEnginePage.CopyImageUrlToClipboard))
                menu.addAction(self.action(QWebEnginePage.CopyImageToClipboard))
            elif media_type == QWebEngineContextMenuData.MediaTypeCanvas:
        #         Q_UNREACHABLE();    // mediaUrl is invalid for canvases
                pass
            elif media_type in [QWebEngineContextMenuData.MediaTypeCanvas,
                                QWebEngineContextMenuData.MediaTypeVideo]:
                menu.addAction(self.action(QWebEnginePage.DownloadMediaToDisk))
                menu.addAction(self.action(QWebEnginePage.CopyMediaUrlToClipboard))
                menu.addAction(self.action(QWebEnginePage.ToggleMediaPlayPause))
                menu.addAction(self.action(QWebEnginePage.ToggleMediaLoop))
                # if (data.mediaFlags() & WebEngineContextMenuData::MediaHasAudio)
                #     menu->addAction(QWebEnginePage::action(ToggleMediaMute));
                # if (data.mediaFlags() & WebEngineContextMenuData::MediaCanToggleControls)
                #     menu->addAction(QWebEnginePage::action(ToggleMediaControls));

        # wrong logic? indent this?
        elif data.mediaType() == QWebEngineContextMenuData.MediaTypeCanvas:
            menu.addAction(self.action(QWebEnginePage.CopyImageToClipboard))

        # if (d->adapter->hasInspector())
        #     menu->addAction(QWebEnginePage::action(InspectElement));

        # if self.adapter.fullscreen:
        #     menu.addAction(self.action(QWebEnginePage.ExitFullScreen))

        text = data.selectedText()

        if text:
            # adv_engines = config.get('content', 'context-advanced-engines')
            adv_engines = config.val.content.context_advanced_engines
            # engines = config.get('content', 'context-engines')
            engines = config.val.content.context_engines

            if urlutils.is_url(text):
                url = urlutils.qurl_from_user_input(text)
                action = QAction('Open Link in New Tab', self,
                                 triggered=functools.partial(self._open_in_tab,
                                                             url))
                menu.insertAction(menu.actions()[0], action)

            item_text = text[:16] + "..." if len(text) > 18 else text

            for engine in engines:
                name, template = urlutils._get_search_engine(engine)
                if name:
                    item_name = '{} "{}"'.format(name, item_text)
                    menu.addAction(item_name, functools.partial(self._search,
                                                                text, engine))

            if adv_engines:
                search_menu = menu.addMenu("Advanced search")
                for engine in adv_engines:
                    name, template = urlutils._get_search_engine(engine)
                    if name:
                        search_menu.addAction(name,
                                              functools.partial(self._search,
                                                                text, engine))

        menu.setAttribute(Qt.WA_DeleteOnClose, True)
        return menu

    @config.change_filter('colors.webpage.bg')
    def _set_bg_color(self):
        col = config.val.colors.webpage.bg
        if col is None:
            col = self._theme_color
        self.setBackgroundColor(col)

    @pyqtSlot(QUrl, 'QWebEnginePage::Feature')
    def _on_feature_permission_requested(self, url, feature):
        """Ask the user for approval for geolocation/media/etc.."""
        options = {
            QWebEnginePage.Geolocation: 'content.geolocation',
            QWebEnginePage.MediaAudioCapture: 'content.media_capture',
            QWebEnginePage.MediaVideoCapture: 'content.media_capture',
            QWebEnginePage.MediaAudioVideoCapture: 'content.media_capture',
        }
        messages = {
            QWebEnginePage.Geolocation: 'access your location',
            QWebEnginePage.MediaAudioCapture: 'record audio',
            QWebEnginePage.MediaVideoCapture: 'record video',
            QWebEnginePage.MediaAudioVideoCapture: 'record audio/video',
        }
        assert options.keys() == messages.keys()

        if feature not in options:
            log.webview.error("Unhandled feature permission {}".format(
                debug.qenum_key(QWebEnginePage, feature)))
            self.setFeaturePermission(url, feature,
                                      QWebEnginePage.PermissionDeniedByUser)
            return

        yes_action = functools.partial(
            self.setFeaturePermission, url, feature,
            QWebEnginePage.PermissionGrantedByUser)
        no_action = functools.partial(
            self.setFeaturePermission, url, feature,
            QWebEnginePage.PermissionDeniedByUser)

        question = shared.feature_permission(
            url=url, option=options[feature], msg=messages[feature],
            yes_action=yes_action, no_action=no_action,
            abort_on=[self.shutting_down, self.loadStarted])

        if question is not None:
            self.featurePermissionRequestCanceled.connect(
                functools.partial(self._on_feature_permission_cancelled,
                                  question, url, feature))

    def _on_feature_permission_cancelled(self, question, url, feature,
                                         cancelled_url, cancelled_feature):
        """Slot invoked when a feature permission request was cancelled.

        To be used with functools.partial.
        """
        if url == cancelled_url and feature == cancelled_feature:
            try:
                question.abort()
            except RuntimeError:
                # The question could already be deleted, e.g. because it was
                # aborted after a loadStarted signal.
                pass

    def shutdown(self):
        self._is_shutting_down = True
        self.shutting_down.emit()

    def certificateError(self, error):
        """Handle certificate errors coming from Qt."""
        self.certificate_error.emit()
        url = error.url()
        error = certificateerror.CertificateErrorWrapper(error)
        log.webview.debug("Certificate error: {}".format(error))

        url_string = url.toDisplayString()
        error_page = jinja.render(
            'error.html', title="Error loading page: {}".format(url_string),
            url=url_string, error=str(error))

        if error.is_overridable():
            ignore = shared.ignore_certificate_errors(
                url, [error], abort_on=[self.loadStarted, self.shutting_down])
        else:
            log.webview.error("Non-overridable certificate error: "
                              "{}".format(error))
            ignore = False

        # We can't really know when to show an error page, as the error might
        # have happened when loading some resource.
        # However, self.url() is not available yet and self.requestedUrl()
        # might not match the URL we get from the error - so we just apply a
        # heuristic here.
        # See https://bugreports.qt.io/browse/QTBUG-56207
        log.webview.debug("ignore {}, URL {}, requested {}".format(
            ignore, url, self.requestedUrl()))
        if not ignore and url.matches(self.requestedUrl(), QUrl.RemoveScheme):
            self.setHtml(error_page)

        return ignore

    def javaScriptConfirm(self, url, js_msg):
        """Override javaScriptConfirm to use qutebrowser prompts."""
        if self._is_shutting_down:
            return False
        escape_msg = qtutils.version_check('5.11', compiled=False)
        try:
            return shared.javascript_confirm(url, js_msg,
                                             abort_on=[self.loadStarted,
                                                       self.shutting_down],
                                             escape_msg=escape_msg)
        except shared.CallSuper:
            return super().javaScriptConfirm(url, js_msg)

    if PYQT_VERSION > 0x050700:
        # WORKAROUND
        # Can't override javaScriptPrompt with older PyQt versions
        # https://www.riverbankcomputing.com/pipermail/pyqt/2016-November/038293.html
        def javaScriptPrompt(self, url, js_msg, default):
            """Override javaScriptPrompt to use qutebrowser prompts."""
            escape_msg = qtutils.version_check('5.11', compiled=False)
            if self._is_shutting_down:
                return (False, "")
            try:
                return shared.javascript_prompt(url, js_msg, default,
                                                abort_on=[self.loadStarted,
                                                          self.shutting_down],
                                                escape_msg=escape_msg)
            except shared.CallSuper:
                return super().javaScriptPrompt(url, js_msg, default)

    def javaScriptAlert(self, url, js_msg):
        """Override javaScriptAlert to use qutebrowser prompts."""
        if self._is_shutting_down:
            return
        escape_msg = qtutils.version_check('5.11', compiled=False)
        try:
            shared.javascript_alert(url, js_msg,
                                    abort_on=[self.loadStarted,
                                              self.shutting_down],
                                    escape_msg=escape_msg)
        except shared.CallSuper:
            super().javaScriptAlert(url, js_msg)

    def javaScriptConsoleMessage(self, level, msg, line, source):
        """Log javascript messages to qutebrowser's log."""
        level_map = {
            QWebEnginePage.InfoMessageLevel: usertypes.JsLogLevel.info,
            QWebEnginePage.WarningMessageLevel: usertypes.JsLogLevel.warning,
            QWebEnginePage.ErrorMessageLevel: usertypes.JsLogLevel.error,
        }
        shared.javascript_log_message(level_map[level], source, line, msg)

    def acceptNavigationRequest(self,
                                url: QUrl,
                                typ: QWebEnginePage.NavigationType,
                                is_main_frame: bool):
        """Override acceptNavigationRequest to forward it to the tab API."""
        type_map = {
            QWebEnginePage.NavigationTypeLinkClicked:
                usertypes.NavigationRequest.Type.link_clicked,
            QWebEnginePage.NavigationTypeTyped:
                usertypes.NavigationRequest.Type.typed,
            QWebEnginePage.NavigationTypeFormSubmitted:
                usertypes.NavigationRequest.Type.form_submitted,
            QWebEnginePage.NavigationTypeBackForward:
                usertypes.NavigationRequest.Type.back_forward,
            QWebEnginePage.NavigationTypeReload:
                usertypes.NavigationRequest.Type.reloaded,
            QWebEnginePage.NavigationTypeOther:
                usertypes.NavigationRequest.Type.other,
        }
        navigation = usertypes.NavigationRequest(url=url,
                                                 navigation_type=type_map[typ],
                                                 is_main_frame=is_main_frame)
        self.navigation_request.emit(navigation)
        return navigation.accepted

    @pyqtSlot('QUrl')
    def _inject_userjs(self, url):
        """Inject userscripts registered for `url` into the current page."""
        if qtutils.version_check('5.8'):
            # Handled in webenginetab with the builtin Greasemonkey
            # support.
            return

        # Using QWebEnginePage.scripts() to hold the user scripts means
        # we don't have to worry ourselves about where to inject the
        # page but also means scripts hang around for the tab lifecycle.
        # So clear them here.
        scripts = self.scripts()
        for script in scripts.toList():
            if script.name().startswith("GM-"):
                log.greasemonkey.debug("Removing script: {}"
                                       .format(script.name()))
                removed = scripts.remove(script)
                assert removed, script.name()

        def _add_script(script, injection_point):
            new_script = QWebEngineScript()
            new_script.setInjectionPoint(injection_point)
            new_script.setWorldId(QWebEngineScript.MainWorld)
            new_script.setSourceCode(script.code())
            new_script.setName("GM-{}".format(script.name))
            new_script.setRunsOnSubFrames(script.runs_on_sub_frames)
            log.greasemonkey.debug("Adding script: {}"
                                   .format(new_script.name()))
            scripts.insert(new_script)

        greasemonkey = objreg.get('greasemonkey')
        matching_scripts = greasemonkey.scripts_for(url)
        for script in matching_scripts.start:
            _add_script(script, QWebEngineScript.DocumentCreation)
        for script in matching_scripts.end:
            _add_script(script, QWebEngineScript.DocumentReady)
        for script in matching_scripts.idle:
            _add_script(script, QWebEngineScript.Deferred)
