import objc
from Foundation import NSObject


class MenuDelegate(NSObject):
    def initWithApp_(self, app):
        self = objc.super(MenuDelegate, self).init()
        if self:
            self.app = app
        return self

    def menuWillOpen_(self, menu):
        if not self.app.is_recording:
            self.app.refresh_files_menus()

