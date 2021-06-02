import socket
import threading
import traceback
from http import HTTPStatus

def parse_address(address):
    try:
        ip = address.split(':')[0]
        port = int(address.split(':')[1])
        return ip, port
    except:
        print('Invalid address [{0}]').format(address)
        print('exception information:')
        print(traceback.format_exc())
        raise ValueError

class BasicTCPServer():
    def __init__(self, address="127.0.0.1:12345", handler=None):
        self.ip, self.port = parse_address(address)

        self.handler = handler if handler is not None else lambda clientsocket, addr:None

        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind((self.ip, self.port))
        self.socket.listen(5)
        self.socket.settimeout(0.5)
        self.terminate = False

    def __del__(self):
        self.stop()

    def set_handler(self, handler):
        self.handler = handler

    def handle_message(self, clientsocket, addr):
        self.handler(clientsocket, addr)
    def loop(self):
        try:
            while not self.terminate:
                try:
                    clientsocket,addr = self.socket.accept()
                    t = threading.Thread(
                        target=self.handle_message, 
                        args=[clientsocket, addr], 
                        name='Client[{0}]'.format(addr),
                        daemon=True
                    )
                    t.start()
                except socket.timeout:
                    pass
        except socket.timeout:
            pass
        except (Exception, KeyboardInterrupt):
            self.socket.close()
            print('ヾ(•ω•`)o')

    def start(self, back=True):
        if back:
            t = threading.Thread(target=self.loop,  name='SocketMainLoop', daemon=True)
            t.start()
        else:
            self.loop()

    def stop(self):
        self.terminate = True
        self.socket.close()

class HTTPBasicHeader():
    def __init__(self, words=None, content=None):
        if content is None:
            content = {}
        self.words = words
        self.content = content

    def encode(self):
        contents = [' '.join([str(w) for w in self.words])]
        contents += ['{0}: {1}'.format(name, value) for name, value in self.content.items()]
        header_message = '\r\n'.join(contents)
        header_message = header_message.encode('utf-8')
        return header_message

    def decode(self, message):
        if type(message) is bytes:
            message = message.decode('utf-8')
        contents = message.split('\r\n')
        contents = [line.strip() for line in contents]
        contents = [line for line in contents if line != '']
        header_line = contents[0]
        contents = contents[1:]
        words = header_line.split(' ')
        valid_contents = {}
        invalid_lines = []
        for line in contents:
            delpos = line.find(':')
            if delpos == -1:
                invalid_lines.append(line)
            else:
                key = line[:delpos].strip()
                value = line[delpos+1:].strip()
                valid_contents[key] = value
        if len(invalid_lines) > 0:
            print('Warning: in-completed line found:')
            print(invalid_lines)
        return words, valid_contents

class InvalidHTTPHeaderError(Exception):
    def __init__(self, message=None):
        pass

class HTTPHeaderDictInterface():
    def __init__(self, content):
        self.content = content
    def __getitem__(self, index):
        return self.content[index]
    def __setitem__(self, index, value):
        self.content[index] = value
    def __contains__(self, index):
        return index in self.content
    def __iter__(self, index):
        for key in self.content:
            yield key

class HTTPRequestHeader(HTTPHeaderDictInterface):
    methods = ['GET', 'HEAD', 'POST', 'PUT', 'DELETE', 'CONNECT', 'OPTIONS', 'TRACE', 'PATCH']
    def __init__(self, method=None, url=None, version='HTTP/1.1', content=None):
        if content is None:
            content = {}
        self.method = method
        self.url = url
        self.version = version
        self.content = content

    def check_valid(self):
        if self.method is None or self.url is None:
            return False
        elif self.method not in HTTPRequestHeader.methods:
            return False
        else:
            return True

    def encode(self):
        if not self.check_valid():
            raise InvalidHTTPHeaderError('Invalid header, method and url should at least be provided.')
        words = [self.method, self.url, self.version]
        content = self.content
        message = HTTPBasicHeader(words=words, content=content).encode()
        return message
    def decode(self, message):
        words, content = HTTPBasicHeader().decode(message)
        if len(words) != 3:
            raise InvalidHTTPHeaderError
        self.method, self.url, self.version = words
        self.content = content

class HTTPResponseHeader(HTTPHeaderDictInterface):
    def __init__(self, code=None, version='HTTP/1.1', content=None):
        if content is None:
            content = {}
        self.code = code
        self.version = version
        self.content = content

    def check_valid(self):
        if self.code is None:
            return False
        else:
            return True

    def encode(self):
        if not self.check_valid():
            raise InvalidHTTPHeaderError('Invalid header, code is required for a http header.')
        words = [self.version, self.code, HTTPStatus(self.code).phrase]
        content = self.content
        message = HTTPBasicHeader(words=words, content=content).encode()
        return message
    def decode(self, message):
        words, content = HTTPBasicHeader().decode(message)
        if len(words) != 3:
            raise InvalidHTTPHeaderError
        self.version, self.code, _ = words
        self.content = content

class SingleHTTPConnection():
    def __init__(self, header, cached, connection):
        self.header = header
        self.connection = connection # connection is a basic socket connection.
        self.cached = cached
        self.length = 0
        if 'Content-Length' in self.header:
            self.length = self.header['Content-Length'] # the remeaning legth of the connection.

    # To ensure all data is send, so we use sendall here.
    def write(self, message):
        self.connection.sendall(message)

    # this function will read fixed length from the socket.
    def read_fixed_size(self, size):
        if size <= 0:
            return b''
        recvd = b''
        while len(recvd) < size:
            this_message = self.connection.recv(size - len(recvd))
            if len(this_message) == 0:
                break
            recvd += this_message
        return recvd

    def read(self, size=None):
        if size is None:
            self.length = 0
            return self.cached + self.read_fixed_size(self.length - self.cached)
        if size > self.length:
            size = self.length
        message = b''
        message = self.cached[:size]
        if len(message) < size:
            message += self.read_fixed_size(size - len(message))
        self.length -= size
        return message

class HTTPBaseServer(BasicTCPServer):
    def __init__(self, request_handler, bind_addr='127.0.0.1:80'):
        if not callable(request_handler):
            raise ValueError('You must provide an callable request handler.')
        super(HTTPBaseServer, self).__init__(address=bind_addr)
        self.request_handler = request_handler

    def handle_message(self, sock, addr):
        # print('processing connection from ', addr)
        # recieve until header ends.
        delemeter = b'\r\n\r\n'
        header_text = b''
        # print('New connection established from', addr)
        while True:
            # wait for the end of the
            while header_text.find(delemeter) == -1:
                this_mesage = sock.recv(8192)
                if len(this_mesage) == 0:
                    # print('connection exited. addr:', addr)
                    return
                header_text += this_mesage
            delpos = header_text.find(delemeter)
            content = header_text[delpos + len(delemeter):]
            header_text = header_text[:delpos]
            header = HTTPRequestHeader()
            header.decode(header_text)
            header_text = b''
            wraped_connection = SingleHTTPConnection(header, content, sock)
            self.request_handler(wraped_connection) # the request handler can only read limited data, once finish, send, and return, we will move on.
            # print('request handler finished.')
