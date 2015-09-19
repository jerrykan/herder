
class MockNull:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            self.__dict__[key] = value

    def __call__(self, *args, **kwargs): return MockNull()
    def __getattr__(self, name):
        # This allows assignments which assume all intermediate steps are Null
        # objects if they don't exist yet.
        #
        # For example (with just 'client' defined):
        #
        # client.db.config.TRACKER_WEB = 'BASE/'
        self.__dict__[name] = MockNull()
        return getattr(self, name)

    def __getitem__(self, key): return self

    # python 3
    def __bool__(self):
        return False

    # need with python 3
    def __contains__(self, value):
        return False

    # python 2
    def __nonzero__(self):
        return False

    def __str__(self): return ''
    def __repr__(self): return '<MockNull 0x%x>'%id(self)
    def gettext(self, str): return str
    _ = gettext
