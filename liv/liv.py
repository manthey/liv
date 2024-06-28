#!/usr/bin/env python3

import argparse
import contextlib
import ctypes
import glob
import logging
import os
import socket
import sys
import threading

import large_image
import numpy as np
import PIL.Image
import PIL.ImageOps

logger = logging.getLogger(__name__)


def find_free_port():
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(('', 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


def start_server(sources, opts):
    import click
    import flask

    def noecho(*args, **kwargs):
        pass

    logging.getLogger('werkzeug').setLevel(max(1, logging.ERROR - (opts.verbose - opts.silent) * 10))
    click.echo = noecho
    click.secho = noecho
    web_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web')
    server = flask.Flask(__name__, static_folder=web_dir, template_folder=web_dir)

    @server.route('/')
    def index():
        return flask.render_template('index.html')

    @server.route('/metadata')
    def metadata():
        return open_source(sources[0], opts).metadata

    @server.route('/zxy/<z>/<x>/<y>')
    def getTile(z, x, y):
        return open_source(sources[0], opts).getTile(int(x), int(y), int(z))

    if not opts.port:
        opts.port = find_free_port()
    logger.info(f'Starting on {opts.host}:{opts.port}')
    if opts.web:
        server.run(
            host=opts.host, port=opts.port,
            use_reloader=(opts.verbose - opts.silent) >= 2,
            extra_files=[os.path.join(web_dir, file) for file in os.listdir(web_dir)],
        )
    else:
        thread = threading.Thread(target=server.run, kwargs=dict(
            host=opts.host, port=opts.port,
        ), daemon=True)
        thread.start()
    return f'http://localhost:{opts.port}'


def show_gui(sources, opts, url):
    import webview

    window = webview.create_window(
        'Large Image Viewer', url)
    menu = [
        webview.menu.Menu('&File', [
            webview.menu.MenuAction('E&xit', window.destroy)
        ]),
    ]
    webview.start(menu=menu)
    """

    import tkinter as tk
    import tkinterweb

    # root window
    root = tk.Tk()
    root.option_add('*tearOff', False)
    root.title('Large Image Viewer')
    # create a menubar
    menubar = tk.Menu(root)
    root.config(menu=menubar)
    # file menu
    file_menu = tk.Menu(menubar)
    file_menu.add_command(label='Exit', command=root.destroy)
    menubar.add_cascade(label='File', menu=file_menu)

    frame = tkinterweb.HtmlFrame(root)  # , messages_enabled=False)
    frame.load_website(url, insecure=True, force=True)
    frame.pack(fill='both', expand=True)

    root.mainloop()
    """


def to_dots(bw):
    at = bw.T.flatten()
    val = sum(2**idx if flat[idx] else 0 for idx in range(8))
    return chr(0x2800 + val)


def to_blocks(blocks, usecolor, x, vblocks):
    fac = [0.3, 0.59, 0.11]
    hdist = sum((float(blocks[1][0][idx]) - blocks[0][0][idx]) ** 2 * fac[idx]
                for idx in range(3))
    vdist = sum((float(vblocks[0][1][idx]) - vblocks[0][0][idx]) ** 2 * fac[idx]
                for idx in range(3))
    # The factor after vdist makes it more pleasing even though technically
    # lower in color resolution
    if hdist <= vdist * 4:
        out = (f'\033[48;2;{blocks[0][0][0]};{blocks[0][0][1]};{blocks[0][0][2]}m'
               f'\033[38;2;{blocks[1][0][0]};{blocks[1][0][1]};{blocks[1][0][2]}m' +
               '\u2584')
    else:
        out = (f'\033[48;2;{vblocks[0][0][0]};{vblocks[0][0][1]};{vblocks[0][0][2]}m'
               f'\033[38;2;{vblocks[0][1][0]};{vblocks[0][1][1]};{vblocks[0][1][2]}m' +
               '\u2590')
    if usecolor is not None:
        if usecolor.get('last', None) == out and x:
            out = usecolor['last'][-1:]
        else:
            usecolor['last'] = out
    return out


# limit this size; maybe add locking at that point
sourceCache = {}


# handle style, etc.
def open_source(source, opts):
    if source in sourceCache:
        return sourceCache[source]
    if getattr(opts, 'usesource', None) is None and getattr(opts, 'skipsource', None) is None:
        ts = large_image.open(source)
    else:
        if not len(large_image.tilesource.AvailableTileSources):
            large_image.tilesource.loadTileSources()
        sublist = {
            k: v for k, v in large_image.tilesource.AvailableTileSources.items()
            if (getattr(opts, 'skipsource', None) is None or k not in opts.skipsource) and
               (getattr(opts, 'usesource', None) is None or k in opts.usesource)}
        ts = large_image.tilesource.getTileSourceFromDict(sublist, source)
        """
        canread = large_image.canReadList(source)
        for src, couldread in canread:
            if getattr(opts, 'skipsource', None) and src in opts.skipsource:
                continue
            if getattr(opts, 'usesource', None) and src not in opts.usesource:
                continue
            ts = large_image.tilesource.AvailableTileSources[src](source)
        """
    sourceCache[source] = ts
    return ts


def image_to_console(source, opts):
    try:
        termw, termh = os.get_terminal_size()
        termh -= 2
    except OSError:
        termw, termh = 80, 25
    if opts.width:
        termw = opts.width
    if opts.height:
        termh = opts.height

    width = termw * 2
    height = termh * 4
    # aspect_ratio = 0.55 * 2
    aspect_ratio = 0.5 * 2
    color = opts.color

    thumbw = width if aspect_ratio < 1 else int(width * aspect_ratio)
    thumbh = height if aspect_ratio > 1 else int(height / aspect_ratio)

    ts = open_source(source, opts)
    img = ts.getThumbnail(
        format=large_image.constants.TILE_FORMAT_PIL, width=thumbw, height=thumbh)[0]
    thumbw, thumbh = img.size

    if aspect_ratio < 1:
        charw, charh = thumbw // 2, int(thumbh * aspect_ratio) // 4
    else:
        charw, charh = int(thumbw / aspect_ratio) // 2, thumbh // 4
    dotw, doth = charw, charh * 2
    if not opts.color:
        dotw, doth = dotw * 2, doth * 2

    adjimg = PIL.ImageOps.autocontrast(img, cutoff=0.02)
    # adjimg = PIL.ImageOps.equalize(img)
    img = PIL.Image.blend(img, adjimg, opts.contrast)

    if opts.color:
        blockimg = np.array(img.convert('RGB').resize((dotw, doth)))
        vblockimg = np.array(img.convert('RGB').resize((dotw * 2, doth // 2)))

        lastcolor = {} if color else None

        output = [
            [to_blocks(blockimg[y:y + 2, x:x + 1], lastcolor, x,
                       vblockimg[y // 2: y // 2 + 1, x * 2: x * 2 + 2])
             for x in range(blockimg.shape[1])]
            for y in range(0, blockimg.shape[0], 2)
        ]
        output = '\033[39m\033[49m\n'.join(''.join(line) for line in output)
        output += '\033[39m\033[49m'
    else:
        blockimg = img.convert('RGB').resize((dotw, doth))
        palimg = np.array(blockimg.convert('P').quantize(
            colors=2, method=PIL.Image.Quantize.MEDIANCUT,
            dither=PIL.Image.Dither.FLOYDSTEINBERG))
        output = [
            [to_dots(1 - palimg[y:y + 4, x:x + 2])
             for x in range(0, palimg.shape[1], 2)]
            for y in range(0, palimg.shape[0], 4)
        ]
        output = '\n'.join(''.join(line) for line in output)
    return output


def show_console(sources, opts):
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:
        pass
    for source in sources:
        sys.stdout.write(f'{source}\n')
        try:
            result = image_to_console(source, opts)
            for line in result.split('\n'):
                sys.stdout.write(line + '\n')
            # sys.stdout.write(result + '\n')
        except Exception:
            pass


def main(opts):
    large_image.tilesource.loadTileSources()
    if opts.all:
        for key in list(large_image.config.ConfigValues):
            if '_ignored_names' in key:
                del large_image.config.ConfigValues[key]
        large_image.config.ConfigValues.pop('all_sources_ignored_names', None)
    sources = get_sources(opts.source)
    if opts.console:
        show_console(sources, opts)
        return
    url = start_server(sources, opts)
    if not opts.web:
        show_gui(sources, opts, url)


def get_sources(sourceList, sources=None):
    sources = set(sources if sources else [])
    for source in sourceList:
        if os.path.isfile(source) or source.startswith(('https://', 'http://')):
            sources.add(source)
        elif os.path.isdir(source):
            for root, _dirs, files in os.walk(source):
                for file in files:
                    sources.add(os.path.join(root, file))
        elif source.startswith('-') and os.path.isfile(source[1:]):
            sources.remove(source[1:])
        elif source.startswith('-') and os.path.isdir(source[1:]):
            for root, _dirs, files in os.walk(source[1:]):
                for file in files:
                    sources.remove(os.path.join(root, file))
        elif not source.startswith('-'):
            sources |= {sourcePath for sourcePath in glob.glob(source)
                        if os.path.isfile(sourcePath)}
        else:
            sources -= {sourcePath for sourcePath in glob.glob(source[1:])
                        if os.path.isfile(sourcePath)}
    sources = sorted(sources)
    return sources


def command():
    parser = argparse.ArgumentParser(description='View large images.')
    parser.add_argument(
        'source', nargs='*', type=str,
        help='Source file to view.  By itself, a separate window is opened '
		'for each file that can be viewed.  This can be a directory for the '
        'entire directory tree, a glob pattern, urls starting with http or '
        'https.  Prefix with - to remove the file, directory, or glob pattern '
        'from the sources analyzed.  Sources are analyzed in a sorted order.')
    parser.add_argument(
        '--verbose', '-v', action='count', default=0, help='Increase verbosity')
    parser.add_argument(
        '--silent', '-s', action='count', default=0, help='Decrease verbosity')
    parser.add_argument(
        '--usesource', '--use', action='append',
        help='Only use the specified source.  Can be specified multiple times.')
    parser.add_argument(
        '--skipsource', '--skip', action='append',
        help='Do not use the specified source.  Can be specified multiple '
        'times.')
    parser.add_argument(
        '--all', action='store_true',
        help='All sources to read all files.  Otherwise, some sources avoid '
        'some files based on name.')

    parser.add_argument(
        '--console', '--con', action='store_true', default=False,
        help='Display in-line on the console.')
    parser.add_argument(
        '--width', '-w', type=int,
        help='Width of the console output; defaults to terminal width.')
    parser.add_argument(
        '--height', type=int,
        help='height of the console output; defaults to terminal width.')
    parser.add_argument(
        '--color', '-c', action='store_true', default=True,
        help='Display in the console in color.')
    parser.add_argument(
        '--no-color', '-n', action='store_false', dest='color',
        help='Do not send color escape codes to the console.')
    parser.add_argument(
        '--contrast', type=float, default=0.25,
        help='Increase the contrast to the console.  0 is no change, 1 is full.')

    parser.add_argument(
        '--host', default='127.0.0.1',
        help='Bind the server to an address.  Use 0.0.0.0 for all.')
    parser.add_argument(
        '--port', type=int,
        help='Bind the server to a port.  Default is an arbitrary open port.')
    parser.add_argument(
        '--web', action='store_true', default=False,
        help='Only start the server, not the menu gui.')
    parser.add_argument(
        '--gui', action='store_false', dest='web',
        help='Show the menu gui.')

    # projection, style, spiff, gallery, sqlite file (gv file), ini file
    opts = parser.parse_args()
    logger.setLevel(max(1, logging.WARNING - (opts.verbose - opts.silent) * 10))
    logger.addHandler(logging.StreamHandler(sys.stderr))
    logger.debug('Command options: %r', opts)
    main(opts)


if __name__ == '__main__':
    command()

# options:
# [Graphic Viewer]
# wed=994560
# Enlarge=0
# Errors=No# Sole=Yes
# LastDir=G:\alt
# WindowPos=0,0,1296,1010
# FileFilter=1
# MatchDepth=No
# Dither=No
# Letterbox=0
# LockSize=8
# Aspect=0,0,1,1
# Topmost=No
# Warnings=Yes
# Margins=1,1,1,1,300,72
# SaveOptions=6,2
# SaveOption0=000000000000000000000000000000000000
# SaveOption1=01009D00000002000000030000000E000E00
# SaveOption2=0100DF050100C00000000000000000000000
# SaveOption3=0000A00000010000803F0200000002000200
# SaveOption4=0300A0000000FF000000FFFFFFFFFFFFFFFF
# SaveOption5=000060000200080000000800000008000800
# SaveOption6=000000000100000000000000000000000000
# SaveOption7=000046000000460000004600000046004600
# SaveOption8=0000A0000000A0000000A0000000A000A000
# SaveOption9=000300000101480A00000000000000000000
# PreviewOptions=3
# MultiOpen=No
# BatchOpen=C:\Orb\grand\high\
# BatchSave=C:\ORB\GRAND\HIGH
# AppendOpen=c:\Temp\b
# AppendSave=c:\Temp\b
# TitleImage=C:\P\W\GV.TIF
# Placement=2C0000000200000003000000FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF000000000000000095020000E2030000
# SlideOpen=G:\
# SlideSave=C:\temp\BigRow
# SlideOptions=535
# SlideDelay=7
# CustomQuant0=0101010101010101010101010102020302020202020403030203050405050504
# CustomQuant1=0404050607060505070604040609060708080808080506090A09080A07080808
# CustomQuant2=0101010202020402020408050405080808080808080808080808080808080808
# CustomQuant3=0808080808080808080808080808080808080808080808080808080808080808
# PreviewWidth=80
# PreviewHeight=60
# PreviewPlacement=2C0000000200000003000000FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFA903000000000000FE040000F9030000
# SortMetric=6,1,1
# CopyDir=C:\temp\oven
# PreviewSaveDir=c:\Temp
# PreviewSaveSize=1500,1500
# RegisterName=David Manthey
# RegisterPassword=RCDSDDTO
# Interpolate=0x2403
# HalfSizeBatch=No
# LastView1=G:\Pic\big+tits_brainparking_eyes_hay_long+hair_milkers_outdoor_straw_tits_3.jpg
# LastView2=G:\Pic\Pslg1110.jpg
# LastView3=G:\Pic\14.jpg
# LastView4=G:\Pic\2649_093.jpg
# SaveDir=c:\temp
# DefaultSaveDir=
# MultiSave=No

# void slide_open(HWND hwnd)
# /* If no slide file is present, present a dialog to select a directory or a
#  *  slide file.  If a slide file is already present, set to auto advance.
#  * A GV Slide file is in the following format:
#  *  byte $0: "GVSlideFileV1.0"
#  *       10: (long) number of file entries
#  *       14: (long) starting location of file entries
#  *       18: (long) compressed length of file entries
#  *       1C: (long) number of directories
#  *       20: (long) starting location of directories
#  *       24: (long) length of directory names, see below
#  *       28: (long) compressed length of directory names
#  *       2C: (long) starting location of file names
#  *       30: (long) length of file names
#  *       34: (long) compressed length of file names
#  *       38: (long) starting location of categories (there are always 30)
#  *       3C: (long) length of category names, see below
#  *       40: (long) compressed length of category names
#  *       44: (long) starting location of thumbnail data
#  *       48: (long) length of thumbnail data
#  *       4C: (long) slide show option flags (SlideOpt flags)
#  *           bit 0: 0-filter to all files, 1-filter to GV slide files
#  *               1: 0-no recurse, 1-recurse
#  *               2: 0-no multiopen, 1-multiopen
#  *               3: 0-manual advance, 1-auto advance
#  *               4: 0-sequential display, 1-random display
#  *               5: 0-preemptive loading, 1-on-demand loading
#  *               6: 0-manual refresh, 1-refresh on loading
#  *               7: 0-track view area, 1-don't track view area
#  *               8: 0-auto save, 1-manual save
#  *               9: 0-new slide file, 1-changing root directory
#  *              10: 0-and category include, 1-or category include
#  *           Preview option flags
#  *              23: 0-show file size, 1-don't show
#  *              24: 0-save selection, 1-save all
#  *              25: 0-make thumbnails, 1-don't make thumbnails
#  *              26: 0-show thumbnail, 1-don't show
#  *              27: 0-show file name, 1-don't show
#  *              28: 0-show categories, 1-don't show
#  *              29: 0-show image size, 1-don't show
#  *              30: 0-show pixel depth, 1-don't show
#  *              31: 0-show only eligible files, 1-show all files
#  *       50: (long) minimum time delay (seconds)
#  *       54: (short) limiting filter number
#  *       56: (2 chars) desired size of thumbnail
#  *       58: (long) length of root directory name
#  *       5C: (char *) root directory
#  *  The file entries are each $48 (72) bytes in length and are of the form:
#  *        0: (short) directory number (0 to numdir-1)
#  *        2: (long) file name (offset within filename data)
#  *        6: (2 shorts) size of original image
#  *        A: (short) pinter of original image
#  *        C: (20 char) file info block as returned by load_graphic
#  *       20: (long) category and viewed data
#  *           bit 0-29: category flags
#  *                 30: viewed flag
#  *                 31: invalid flag - set if this is not a valid graphic file
#  *       24: (4 shorts) selected region of picture
#  *       2C: (2 chars) size of thumbnail
#  *       2E: (char) palettization of thumbnail (0-24 bit, 1-8 bit)
#  *       2F: (char) scale and select flags
#  *           bit 0: 0-scaled from orginal, 1-actual size
#  *               1: 0-not selected, 1-selected
#  *               2: 0-selection not changing, 1-selection changing
#  *       30: (long) location of thumbnail (offset within thumbnail data)
#  *       34: (long) length of thumbnail
#  *       38: (long) length of file
#  *       3C: (short) file time.  Bits 0-4: seconds/2 (0-29), 5-10: minute
#  *                   (0-59), 11-15: hour (0-23).
#  *       3E: (short) file date.  Bits 0-4: day (0-31), 5-8: month (1-12),
#  *                   9-15: year-1980
#  *       40: (long) position in preview or -1 for not in preview
#  *       44: (long) used for sort
#  *  The directories have a header followed by a text strike of each name:
#  *        0: (long) location of text (offset from start of text strike)
#  *        4: (short) length of text (including terminating null)
#  *    6*numdir: text strike
#  *  The file names are stored as a text strike.
#  *  The categories have a header followed by a text strike of each name:
#  *        0: (long) location of text (offset from start of text strike)
#  *        4: (short) length of text (including terminating null).  Zero for
#  *           category not defined.
#  *        6: (char) Associated quick key, 0 for none, 1-10 for '0'-'9'.
#  *        7: (char) Show property: 0-doesn't matter, 1-include, 2-exclude
#  *     8*30: text strike (note that there are exactly 30 categories)
#  *  The thumbnail data is referenced by the file entries.  Each thumbnail is
#  *   of the form:
#  *        0: lzw compressed RGB picture of the size specified in file entry.
#  *  Within the file, file, directory, and category names are LZW compressed.
#  *   This is both to save space and to keep undesirable file names hidden.
#  * SlideOpt contains the same flags as the slide show file.

# Menus
# File
#  Open... ^O
#  Open New... ^N   (open in another window)
#  Open All Parts (boolean)
#  ---
#  First Image ^PgUp
#  Previous Image PgUp
#  Next Image PgDn
#  ---
#  Save... ^S
#  Save As... ^A
#  Save All Parts (boolean)
#  Append... ^D
#  ---
#  Batch Convert... ^B
#  Batch Append...
#  ---
#  Print... ^P
#  Page Setup...
#  ---
#  Exit Alt+F4
#  ---
#  <Recent files>
# Edit
#  Undo ^Z
#  ---
#  Copy Whole Image ^C
#  Copy View ^X
#  Paste ^V
#  ---
#  Refresh Screen `
# Slide
#  New/Open Slide Show S
#  Save Slide File
#  Save As Slide File...
#  Close Slide File
#  ---
#  Slide Options... O
#  Preview P
#  ---
#  Increase Delay - <n seconds> +
#  Descrease Delay -
#  Manual Advance (pause) M
#  Auto Advance A
#  Clear View Record C
#  Next File N
#  Next Slide space
#  Next Slide Group ^space
#  ---
#  <categories>
# Zoom
#  Whole Picture W
#  Enlarge E
#  Reduce R
#  ---
#  Original Size ^0
#  25% Size ^3
#  50% Size ^5
#  100% Size ^1
#  200% Size ^2
#  400% Size ^4
#  ---
#  Bigger ^+
#  Smaller ^-
#  ---
#  Lock Aspect Ratio... ^8
#  78x110 Aspect Ratio ^7
# Options
#  Letter&boxing
#   Fit Window
#   ---
#   Black
#   Grey
#   White
#   Contrasting
#  Display
#   Greyscale
#   Reduce Color Depth
#   Dither
#   Bilinear Interpolate
#   Bicubic Interpolate
#   Spiff F
#   Turn Off Spiff shift-F
#  ---
#  Rotate Clockwise >
#  Rotate Counterclockwise <
#  ---
#  Lock Window Size
#  Prevent Enlarge
#  Lock 100% Size
#  ---
#  Error Messages
#  Warning Messages
#  Sole Process
#  Always On Top
#  ---
#  Link Extensions
# Help
#  Image Info... ^I
#  ---
#  Help... F1
#  Search Help...
#  ---
#  About...

# Slide Menus
# File
#  New/Open Preview File... ^O
#  Save Preview File... ^S
#  Save Preview File As... ^A
#  ---
#  Save Preview Screens... Z
#  ---
#  Print... ^P
#  Print Setup...
#  ---
#  Exit Preview Alt-F4
# Edit
#  Copy Whole Preview ^C
#  Copy Selection ^X
#  ---
#  Select All
#  Select None ^D
#  ---
#  Refresh Screen `
# Preview
#  Slide Show S
#  ---
#  Slide Options... O
#  Preview Options... I
#  Make thumbnails A
#  Stop making thumbnails Esc
#  Delete thumbnails
#  ---
#  Mark as viewed V
#  Clear viewed flag C
#  ---
#  <categories>
# Image
#  Show Enter
#  ---
#  Copy
#  Delete ^Del
#  Move
#  Rename
#  ---
#  Sort T
#  Find ^F
#  Find Again ^G
# Help
#  Image Info... ^I
#  ---
#  Help... F1
#  Search Help...
#  ---
#  About...

# https://github.com/prabhuignoto/vue-float-menu
# https://floating-vue.starpad.dev/api/
