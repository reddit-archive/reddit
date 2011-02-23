import sys
from r2.lib.mr_tools._mr_tools import mr_reduce, format_dataspec

def join_things(fields, deleted=False, spam=True):
    """A reducer that joins thing table dumps and data table dumps"""
    def process(thing_id, vals):
        data = {}
        thing = None

        for val in vals:
            if val[0] == 'thing':
                thing = format_dataspec(val,
                                        ['data_type', # e.g. 'thing'
                                         'thing_type', # e.g. 'link'
                                         'ups',
                                         'downs',
                                         'deleted',
                                         'spam',
                                         'timestamp'])
            elif val[0] == 'data':
                val = format_dataspec(val,
                                      ['data_type', # e.g. 'data'
                                       'thing_type', # e.g. 'link'
                                       'key', # e.g. 'sr_id'
                                       'value'])
                if val.key in fields:
                    data[val.key] = val.value

        if (
            # silently ignore if we didn't see the 'thing' row
            thing is not None

            # remove spam and deleted as appriopriate
            and (deleted or thing.deleted == 'f')
            and (spam or thing.spam == 'f')

            # and silently ignore items that don't have all of the
            # data that we need
            and all(field in data for field in fields)):

            yield ((thing_id, thing.thing_type, thing.ups, thing.downs,
                    thing.deleted, thing.spam, thing.timestamp)
                   + tuple(data[field] for field in fields))

    mr_reduce(process)

def test():
    from r2.lib.mr_tools._mr_tools import keyiter

    for key, vals in keyiter():
        print key, vals
        for val in vals:
            print '\t', val
