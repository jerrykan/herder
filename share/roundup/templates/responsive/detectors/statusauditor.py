def preset_new(db, cl, nodeid, newvalues):
    """ Make sure the status is set on new bugs"""

    if newvalues.get('status'):
        return

    new = db.status.lookup('new')
    newvalues['status'] = new


def init(db): pass
    # fire before changes are made
    #db.bug.audit('create', preset_new)
