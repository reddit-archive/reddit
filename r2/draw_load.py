from __future__ import with_statement
import Image, ImageDraw

colors = [
    "#FFFFFF", "#f0f5FF", 
    "#E2ECFF", "#d6f5cb", 
    "#CAFF98", "#e4f484", 
    "#FFEA71", "#ffdb81", 
    "#FF9191", "#FF0000"]

def get_load_level(host, nlevels = 8):
     # default number of cpus shall be 1
     ncpus = getattr(host, "ncpu", 1)
     # color code in nlevel levels
     return _load_int(host.load(), ncpus, nlevels = 8)

def _load_int(current, max_val, nlevels = 8):
     i =  min(max(int(nlevels*current/max_val+0.4), 0),nlevels+1)
     return colors[i]

def draw_load(row_size = 12, width = 200, out_file = "/tmp/load.png"):
    from r2.lib import services
    
    a = services.AppServiceMonitor()
    hosts = list(a)
    
    number = (len([x for x in hosts if x.services]) + 
              len([x for x in hosts if x.database]) +
              sum(len(x.queue.queues) for x in hosts if x.queue)) + 9

    im = Image.new("RGB", (width, number * row_size + 3))
    draw = ImageDraw.Draw(im)
    def draw_box(label, color, center = False):
        ypos = draw_box.ypos
        xpos = 1
        if center:
            w, h = draw.textsize(label)
            xpos = (width - w) / 2
        draw.rectangle(((1, ypos), (width-2, ypos + row_size)), color)
        draw.text((xpos,ypos+1), label, fill = "#000000")
        draw_box.ypos += row_size
    draw_box.ypos = 0

    draw_box(" ==== DATABASES ==== ", "#BBBBBB", center = True)
    for host in hosts:
        if host.database:
            draw_box("  %s load: %s" % (host.host, host.load()),
                     get_load_level(host))

    draw_box(" ==== SERVICES ==== ", "#BBBBBB", center = True)
    for host in hosts:
        if host.host.startswith('app'):
            draw_box("  %s load: %s" % (host.host, host.load()),
                     get_load_level(host))

    draw_box(" ==== BUTTONS ==== ", "#BBBBBB", center = True)
    for host in hosts:
        if host.host.startswith('button'):
            draw_box("  %s load: %s" % (host.host, host.load()),
                     get_load_level(host))

    draw_box(" ==== MEDIA ==== ", "#BBBBBB", center = True)
    for host in hosts:
        if host.host.startswith('media'):
            draw_box("  %s load: %s" % (host.host, host.load()),
                     get_load_level(host))
    draw_box(" ==== SEARCH ==== ", "#BBBBBB", center = True)
    for host in hosts:
        if host.host.startswith('search'):
            draw_box("  %s load: %s" % (host.host, host.load()),
                     get_load_level(host))

    draw_box(" ==== CACHES ==== ", "#BBBBBB", center = True)
    for host in hosts:
        if (host.host.startswith('cache') or host.host.startswith('pmc') or
            host.host.startswith('url')):
            draw_box("  %s load: %s" % (host.host, host.load()),
                     get_load_level(host))

    draw_box(" ==== QUEUES ==== ", "#BBBBBB", center = True)
    for host in hosts:
        if host.queue:
            draw_box("  %s load: %s" % (host.host, host.load()),
                     get_load_level(host))
            for name, data in host.queue:
                max_len = host.queue.max_length(name)
                draw_box(" %16s: %5s / %5s" % (name, data(), max_len),
                         _load_int(data(), max_len))

    with open(out_file, 'w') as handle:
        im.save(handle, "PNG")
    

def merge_images(out_file, file_names):
    images = []
    width = 0
    height = 0
    for f in file_names:
        images.append(Image.open(f))
        w, h = images[-1].size
        width = max(w, width)
        height += h

    total = Image.new("RGB", (width, height))
    height = 0
    for im in images:
        total.paste(im, (0, height))
        w, h = im.size
        height += h

    with open(out_file, 'w') as handle:
        total.save(out_file)
    
