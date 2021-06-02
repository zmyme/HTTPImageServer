import os
import io
import json
import time

import threading
import queue
from http import HTTPStatus
from urllib.parse import unquote
from PIL import Image

from network import HTTPBaseServer, HTTPResponseHeader

app_dir = os.path.split(os.path.realpath(__file__))[0]
index_path = os.path.join(app_dir, 'index.html')

def loadfile(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()

class HTTPImageServer():
    def __init__(self, bind_addr, imgroot='.', thumbnail='webp', allowcros=True, loglevel=2):
        self.server = HTTPBaseServer(request_handler=self.handle, bind_addr=bind_addr)
        self.imgroot = imgroot
        self.img_extension = ['png', 'jpg', 'jpeg', 'tiff', 'webp', 'bmp']
        self.print_lock = threading.Lock()
        self.logqueue = queue.Queue()
        self.thumbnail = thumbnail
        self.allowcros = allowcros
        self.loglevel = loglevel # 0: all information 1: only for response. 2: do not log image file. 3: no log.
    def start(self, back=True):
        t = threading.Thread(target=self.logger, name='Logger thread', daemon=True)
        t.start()
        self.server.start(back=back)
        
    
    def logger(self):
        while True:
            try:
                msg = self.logqueue.get(timeout=1)
                print(msg)
            except queue.Empty:
                pass

    @staticmethod
    def parse_url(url):
        location = url.split('?')[0]
        params_str = url[len(location)+1:]
        location = unquote(location)
        params = {}
        splits = params_str.split('&')
        for split in splits:
            split = unquote(split)
            eq_pos = split.find('=')
            if eq_pos == -1:
                params[split] = None
                continue
            else:
                key = split[:eq_pos]
                value = split[eq_pos+1:]
                params[key] = value
        return location, params
    
    def log(self, msg):
        self.logqueue.put(msg)
    
    def response(self, connection, header, content, loglevel=1):
        if loglevel >= self.loglevel:
            msg = '[{time}] {method}: {url} - {stat}'.format(
                time = time.strftime("%H:%M:%S", time.localtime()),
                method = connection.header.method,
                url = connection.header.url,
                stat = '{0}({1})'.format(header.code, HTTPStatus(header.code).phrase)
            )
            self.log(msg)
        
        header['Content-Length'] = len(content)
        if self.allowcros:
            header['Access-Control-Allow-Origin'] = '*'
        connection.write(header.encode() + b'\r\n\r\n')
        connection.write(content)

    def response_404(self, connection):
        header = HTTPResponseHeader(404)
        content = b'404 Not Found'
        self.response(connection, header, content)
    @staticmethod
    def safe_path(path):
        path = '/'.join(path.split('\\'))
        path = path.split('/')
        path = [p for p in path if p not in ['', '..', '.']]
        path = '/'.join(path)
        return path

    
    def handle_index(self, params):
        if 'path' not in params:
            return HTTPResponseHeader(404), b'404 Not Found'
        directory = params['path']
        while '\\' in directory:
            directory = directory.replace('\\', '/')
        directory = self.safe_path(directory)
        disk_directory = os.path.join(self.imgroot, directory)
        filenames = []
        try:
            filenames = os.listdir(disk_directory)
            filenames.sort()
        except Exception:
            pass
        response = {"dirs": [], "imgs": []}
        for filename in filenames:
            full_path = os.path.join(disk_directory, filename)
            request_path = '/{0}/{1}'.format(directory, filename)
            request_path = '/' + request_path.strip('/\\')
            if os.path.isdir(full_path):
                response['dirs'].append(request_path)
            else:
                if filename.split('.')[-1] in self.img_extension:
                    response['imgs'].append(request_path)
        response = json.dumps(response).encode('utf-8')
        return HTTPResponseHeader(200), response
    
    def handle_image(self, params):
        invalid_request = False
        if 'path' not in params:
            invalid_request = True
        filepath = params['path']
        filepath = self.safe_path(filepath)
        full_path = os.path.join(self.imgroot, filepath)
        if filepath.split('.')[-1] not in self.img_extension:
            invalid_request = True
        elif not os.path.isfile(full_path):
            invalid_request = True
        
        # parse height and width limit.
        max_h, max_w = None, None
        try:
            if 'height' in params:
                max_h = int(params['height'])
            elif 'width' in params:
                max_w = int(params['width'])
        except Exception:
            invalid_request = True
    
        if invalid_request:
            return HTTPResponseHeader(404), b'404 Not Found'

        header = HTTPResponseHeader(200)
        content = b''
        if max_h is not None or max_w is not None:
            img = Image.open(full_path)
            real_w, real_h = img.size
            h_ratio = None
            w_ratio = None
            if max_h is not None:
                h_ratio = max_h / real_h
                h_ratio = h_ratio if h_ratio < 1 else 1
            if max_w is not None:
                w_ratio = max_w / real_w
                w_ratio = w_ratio if w_ratio < 1 else 1
            max_ratio = 0
            if h_ratio is None:
                max_ratio = w_ratio
            elif w_ratio is None:
                max_ratio = h_ratio
            else:
                max_ratio = h_ratio if h_ratio < w_ratio else w_ratio
            new_h, new_w = (real_h * max_ratio, real_w * max_ratio)
            img = img.resize((int(new_w), int(new_h)))
            img_stream = io.BytesIO()
            img = img.save(img_stream, format=self.thumbnail)
            content = img_stream.getvalue()
        else:
            with open(full_path, 'rb') as f:
                content = f.read()
        return header, content
        

    """
    request_type:
    request index: http://domain.com/directory?path=relative/path/to/file
    request image: http://domain.com/img?path=relative/path/to/file&height=100px&width=200px
    """
    def handle(self, connection):
        method = connection.header.method
        if method != 'GET':
            self.response_404(connection)
            return
        
        url = connection.header.url
        location, params = self.parse_url(url)
        location = location.strip('/\\')
        header, content = None, None
        loglevel = 0
        if location == 'directory':
            header, content = self.handle_index(params)
            loglevel = 2
        elif location == 'img':
            header, content = self.handle_image(params)
            loglevel = 1
        elif location in ['', 'index', 'index.html']:
            header = HTTPResponseHeader(200)
            content = loadfile(index_path).encode('utf-8')
            loglevel = 2
        else:
            header = HTTPResponseHeader(404)
            content = b'Please Do Not Try To Access Non-Image File!'
            loglevel = 2
        self.response(connection, header, content, loglevel=loglevel)

def str2bool(string):
    positive = ['true',
        't',
        'y',
        'yes',
        '1',
        'correct',
        'accept',
        'positive'
    ]
    if string.lower() in positive:
        return True
    else:
        return False

if __name__ == '__main__':
    import sys
    import argparse
    import json
    args= sys.argv[1:]

    parser = argparse.ArgumentParser('HTTPImageServer')
    conf_path = 'config.json'

    # load default configuration first.
    defaults = {
        "port": 80,
        "interface": "0.0.0.0",
        "root": ".",
        "thumbnail": "webp",
        "cros": True,
        "loglevel": 2,
    }
    config = defaults
    if os.path.isfile(conf_path):
        with open(conf_path, 'r', encoding='utf-8') as f:
            config.update(json.load(f))
    else:
        with open(conf_path, 'w+', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        

    parser.add_argument('--port', '-p', type=int, default=None, help='which port to start server on.')
    parser.add_argument('--interface', '-i', type=str, default=None, help='which interface to bind, default is 0.0.0.0 for all interface.')
    parser.add_argument('--root', '-r', type=str, default=None, help='root directory, default is current directory.')
    parser.add_argument('--thumbnail', '-t', type=str, default=None, help='thumbnail format, default is webp, if you have any trouble, change to jpeg.')
    parser.add_argument('--cros', type=str2bool, default=None, help='disable cros. default is enabled.')
    parser.add_argument('--loglevel', '-l', type=int, default=None, help='loglevel, 0: all information 1: only for response. 2: do not log image file. 3: no log.')
    parser.add_argument('--save', default=False, action='store_true', help='save the configuration as default.')
    args = parser.parse_args()
    parsed = {key:value for key, value in args.__dict__.items() if value is not None}
    config.update(parsed)
    args.__dict__.update(config)
    if args.save:
        config.pop('save')
        with open(conf_path, 'w+', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)

    addr = '{0}:{1}'.format(args.interface, args.port)
    print('Start HTTP server on {0} and use web root as {1}'.format(addr, args.root))
    server = HTTPImageServer(bind_addr=addr, imgroot=args.root, thumbnail=args.thumbnail, allowcros=args.cros, loglevel=args.loglevel)
    server.start(back=False)
