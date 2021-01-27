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
    def __init__(self, bind_addr, imgroot='.'):
        self.server = HTTPBaseServer(request_handler=self.handle, bind_addr=bind_addr)
        self.imgroot = imgroot
        self.img_extension = ['png', 'jpg', 'jpeg', 'tiff', 'webp', 'bmp']
        self.print_lock = threading.Lock()
        self.logqueue = queue.Queue()
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
    
    def response(self, connection, header, content):
        msg = '[{time}] {method}: {url} - {stat}'.format(
            time = time.strftime("%H:%M:%S", time.localtime()),
            method = connection.header.method,
            url = connection.header.url,
            stat = '{0}({1})'.format(header.code, HTTPStatus(header.code).phrase)
        )
        self.log(msg)
        
        header['Content-Length'] = len(content)
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
            img = img.save(img_stream, format='webp')
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
        if location == 'directory':
            header, content = self.handle_index(params)
        elif location == 'img':
            header, content = self.handle_image(params)
        elif location in ['', 'index', 'index.html']:
            header = HTTPResponseHeader(200)
            content = loadfile(index_path).encode('utf-8')
        else:
            header = HTTPResponseHeader(404)
            content = b'Please Do Not Try To Access Non-Image File!'
        self.response(connection, header, content)

if __name__ == '__main__':
    import sys
    args= sys.argv[1:]

    port = 80
    root = '.'
    if len(args) > 0:
        try:
            port = int(args[0])
        except Exception:
            print('Port {0} not understood, use 80 instead'.format(args[0]), file=sys.stderr)
    if len(args) > 1:
        root = args[1]
        if not os.path.isdir(root):
            print('Path {0} is not a valid path, use current directory instead.'.format(root), file=sys.stderr)
            root = '.'

    print('Start HTTP server on port {0} and use web root as {1}'.format(port, root))
    server = HTTPImageServer(bind_addr='0.0.0.0:{0}'.format(port), imgroot=root)
    server.start(back=False)
