def test_cassasavehide():
    from r2.models import Account, Link, CassandraSave, SavesByAccount
    from r2.lib.db import tdb_cassandra

    a = list(Account._query(sort=desc('_date'),
                            limit=1))[0]
    l = list(Link._query(sort=desc('_date'),
                         limit=1))[0]

    try:
        csh = CassandraSave._fast_query(a._id36, l._id36)
        print "Warning! Deleting!", csh
        CassandraSave._fast_query(a._id36, l._id36)._destroy()
    except tdb_cassandra.NotFound:
        pass

    csh = CassandraSave._save(a, l)
    csh._commit()
    assert CassandraSave._fast_query(a._id36, l._id36) == csh

    # check for the SavesByAccount object too
    assert SavesByAccount._byID(a._id36)[csh._id] == csh._id

    csh._destroy()

    try:
        CassandraSave._fast_query(a._id36, l._id36) == csh
        raise Exception("shouldn't exist after destroying")
    except tdb_cassandra.NotFound:
        pass

    try:
        assert csh._id not in SavesByAccount._byID(a._id36, properties = csh._id)._values()
    except tdb_cassandra.NotFound:
        pass
