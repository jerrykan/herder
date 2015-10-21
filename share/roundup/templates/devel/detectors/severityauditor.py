
def init_severity(db, cl, nodeid, newvalues):
    """Make sure severity is set on new bugs"""
    if newvalues.get('severity'):
        return

    normal = db.severity.lookup('normal')
    newvalues['severity'] = normal

def init(db): pass
    #db.bug.audit('create', init_severity)
