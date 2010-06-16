import sys

class LineReader(object):
    """A simple class to read lines from a File (like stdin) that
       supports pushing lines back into the buffer"""
    def __init__(self, stream):
        self.stream = stream
        self.pushed_back = []

    def readline(self):
        if self.pushed_back:
            return self.pushed_back.pop()
        else:
            return self.stream.readline()

    def push_back(self, line):
        self.pushed_back.append(line)

def in_chunks(it, size=25):
    chunk = []
    it = iter(it)
    try:
        while True:
            chunk.append(it.next())
            if len(chunk) >= size:
                yield chunk
                chunk = []
    except StopIteration:
        if chunk:
            yield chunk

def valiter(key, lr, firstline):
    line = firstline
    while line:
        linevals = line.strip('\n').split('\t')
        readkey, vals = linevals[0], linevals[1:]
        if readkey == key:
            yield vals
            line = lr.readline()
        else:
            lr.push_back(line)
            line = None

def keyiter(stream):
    lr = LineReader(stream)

    line = lr.readline()
    while line:
        key = line.strip('\n').split('\t',1)[0]

        vi = valiter(key, lr, line)
        yield key, vi
        # read the rest of the valueiter before reading any more lines
        try:
            while vi.next():
                pass
        except StopIteration:
            pass

        line = lr.readline()

def status(msg, **opts):
    if opts:
        msg = msg % opts
    sys.stderr.write("%s\n" % msg)

def emit(vals):
    print '\t'.join(str(val) for val in vals)

def emit_all(vals):
    for val in vals:
        emit(val)

class Storage(dict):
    def __getattr__(self, attr):
        return self[attr]

def format_dataspec(msg, specs):
    # spec() =:= name | (name, fn)
    # specs  =:= [ spec() ]
    ret = Storage()
    for val, spec in zip(msg, specs):
        if isinstance(spec, basestring):
            name = spec
            ret[name] = val
        else:
            name, fn = spec
            ret[name] = fn(val)
    return Storage(**ret)

class dataspec_m(object):
    def __init__(self, *specs):
        self.specs = specs

    def __call__(self, fn):
        specs = self.specs
        def wrapped_fn(args):
            return fn(format_dataspec(args, specs))
        return wrapped_fn

class dataspec_r(object):
    def __init__(self, *specs):
        self.specs = specs

    def __call__(self, fn):
        specs = self.specs
        def wrapped_fn(key, msgs):
            return fn(key, ( format_dataspec(msg, specs)
                             for msg in msgs ))
        return wrapped_fn

def mr_map(process, fd = sys.stdin):
    for line in fd:
        vals = line.strip('\n').split('\t')
        for res in process(vals):
            emit(res)

def mr_reduce(process, fd = sys.stdin):
    for key, vals in keyiter(fd):
        for res in process(key, vals):
            emit(res)

def mr_foldl(process, init, emit = False, fd = sys.stdin):
    acc = init
    for key, vals in keyiter(fd):
        acc = process(key, vals, acc)

    if emit:
        emit(acc)

    return acc
            
def mr_max(process, idx = 0, num = 10, emit = False, fd = sys.stdin):
    """a reducer that, in the process of reduction, only returns the
       top N results"""
    maxes = []
    for key, vals in keyiter(fd):
        for newvals in in_chunks(process(key, vals)):
            for val in newvals:
                if len(maxes) < num or newval[idx] > maxes[-1][idx]:
                    maxes.append(newval)
            maxes.sort(reverse=True)
            maxes = maxes[:num]

    if emit:
        emit_all(maxes)

    return maxes

def mr_reduce_max_per_key(sort_key, post = None, num = 10, fd = sys.stdin):
    def process(key, vals):
        maxes = []
        for val_chunk in in_chunks(vals, num):
            maxes.extend(val_chunk)
            maxes.sort(reverse=True, key=sort_key)
            maxes = maxes[:num]
        if post:
            # if we were passed a "post" function, he takes
            # responsibility for emitting
            post(key, maxes)
        else:
            for item in maxes:
                yield [key] + item

    return mr_reduce(process, fd = fd)

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

def dataspec_m_rel(*fields):
    return dataspec_m(*((('rel_id', int),
                         'rel_type',
                         ('thing1_id', int),
                         ('thing2_id', int),
                         'name',
                         ('timestamp', float))
                        + fields))

def dataspec_m_thing(*fields):
    return dataspec_m(*((('thing_id', int),
                         'thing_type',
                         ('ups', int),
                         ('downs', int),
                         ('deleted', lambda x: x == 't'),
                         ('spam', lambda x: x == 't'),
                         ('timestamp', float))
                        + fields))

if __name__ == '__main__':
    for key, vals in keyiter(sys.stdin):
        print key, vals
        for val in vals:
            print '\t', val
