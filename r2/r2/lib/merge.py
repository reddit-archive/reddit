import subprocess
import tempfile
import difflib
from pylons.i18n import _
from pylons import g

class ConflictException(Exception):
    def __init__(self, new, your, original):
        self.your = your
        self.new = new
        self.original = original
        self.htmldiff = make_htmldiff(new, your, _("current edit"), _("your edit"))
        Exception.__init__(self)


def make_htmldiff(a, b, adesc, bdesc):
    diffcontent = difflib.HtmlDiff(wrapcolumn=60)
    return diffcontent.make_table(a.splitlines(),
                                  b.splitlines(),
                                  fromdesc=adesc,
                                  todesc=bdesc)

def threeWayMerge(original, a, b):
    try:
        temp_dir = g.diff3_temp_location if g.diff3_temp_location else None
        data = [a, original, b]
        files = []
        for d in data:
            f = tempfile.NamedTemporaryFile(dir=temp_dir)
            f.write(d.encode('utf-8'))
            f.flush()
            files.append(f)
        try:
            final = subprocess.check_output(["diff3", "-a", "--merge"] + [f.name for f in files])
        except subprocess.CalledProcessError:
            raise ConflictException(b, a, original)
    finally:
        for f in files:
            f.close()
    return final.decode('utf-8')

if __name__ == "__main__":
    class test_globals:
        diff3_temp_location = None
    
    g = test_globals()
    
    original = "Hello people of the human rance\n\nHow are you tday"
    a = "Hello people of the human rance\n\nHow are you today"
    b = "Hello people of the human race\n\nHow are you tday"
    
    print threeWayMerge(original, a, b)
    
    g.diff3_temp_location = '/dev/shm'
    
    print threeWayMerge(original, a, b)
