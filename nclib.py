"""
Netcat as a library
This is Python3 adapted version of https://github.com/rhelmot/nclib
The goal of this lib is to have a tool like telnetlib but without the telnet specific problems

"""
import sys, select, os, socket, string, time

__all__ = ('NetcatError', 'Netcat')

class NetcatError(Exception):
    pass

class Netcat(object):
    """
    Example usage:

    Send a greeting to a UDP server listening at 192.168.3.6:8888 and log the
    response as hex:
    >>> nc = nclib.Netcat(('192.168.3.6', 8888), udp=True, verbose=True)
    >>> nc.echo_hex = True
    >>> nc.echo_sending = False
    >>> nc.send('Hello, world!')
    >>> nc.recv_all()

    Listen for a local TCP connection on port 1234, allow the user to interact
    with the client. Log the entire interaction to log.txt.
    >>> logfile = open('log.txt', 'wb')
    >>> nc = nclib.Netcat(listen=('localhost', 1234), log_send=logfile, log_recv=logfile)
    >>> nc.interact()
    """
    def __init__(self, server=None, sock=None, listen=None, udp=False, verbose=0, log_send=None, log_recv=None):
        """
        One of the following must be passed in order to initialize a Netcat object:

        sock:        a python socket object to wrap
        server:      a tuple (host, port) to connect to
        listen:      a tuple (host, port) to bind to for listening

        Additionally, the following options modify the behavior of the object:

        udp:         Set to True to use udp connections when using the server or listen methods
        verbose:     Set to True to log data sent/received. The echo_* properties on this object
                     can be tweaked to describe exactly what you want logged.
        log_send:    Pass a file-like object open for writing and all data sent over the socket
                     will be duplicated to the file.
        log_send:    Pass a file-like object open for writing and all data recieved from the will
                     be logged to it.
        """
        self.buf = b''
        if sock is None:
            self.sock = socket.socket(type=socket.SOCK_DGRAM if udp else socket.SOCK_STREAM)
            if server is not None:
                self.sock.connect(server)
                self.peer = server
                self.peer_implicit = True
            elif listen is not None:
                self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.sock.bind(listen)
                if not udp:
                    self.sock.listen(1)
                    conn, addr = self.sock.accept()
                    self.sock.close()
                    self.sock = conn
                    self.peer = addr
                    self.peer_implicit = True
                else:
                    self.buf, self.peer = self.sock.recvfrom(1024)
                    self.peer_implicit = False
                if verbose:
                    print('Connection from %s accepted' % str(self.peer))
            else:
                raise ValueError('Not enough arguments, need at least a server or a socket or a listening address!')
        else:
            self.sock = sock
            self.peer_implicit = True

        self.verbose = verbose
        self.log_send = log_send
        self.log_recv = log_recv
        self.echo_headers = True
        self.echo_perline = True
        self.echo_sending = True
        self.echo_recving = True
        self.echo_hex = False
        
        self._timeout = None    # for settimeout
        self.timed_out = False  # set when an operation times out

    def _head_buf(self, index=None):
        if index is None:
            index = len(self.buf)
        ret = self.buf[:index]
        self.buf = self.buf[index:]
        return ret

    def close(self):
        """
        Close the socket.
        """
        return self.sock.close()

    def shutdown(self, how=socket.SHUT_RDWR):
        """
        Send a shutdown signal for both reading and writing, or whatever
        socket.SHUT_* constant you like.

        Shutdown differs from closing in that it explicitly changes the state of
        the socket resource to closed, whereas closing will only decrement the
        number of peers on this end of the socket, since sockets can be a resource
        shared by multiple peers on a single OS. When the number of peers reaches zero,
        the socket is closed, but not deallocated, so you still need to call close.
        (except that this is python and close is automatically called on the deletion
        of the socket)

        http://stackoverflow.com/questions/409783/socket-shutdown-vs-socket-close
        """
        return self.sock.shutdown(how)

    def shutdown_rd(self):
        """
        Send a shutdown signal for reading - you may no longer read from this socket
        """
        return self.shutdown(socket.SHUT_RD)

    def shutdown_wr(self):
        """
        Send a shutdown signal for reading - you may no longer write to this socket
        """
        return self.shutdown(socket.SHUT_WR)

    def fileno(self):
        """
        Return the file descriptor associated with this socket
        """
        return self.sock.fileno()

    def _log_something(self, data, prefix):
        if self.echo_perline:
            if self.echo_hex:
                self._print_hex_lines(data, prefix)
            else:
                self._print_lines(data, prefix)
        else:
            if self.echo_hex:
                sys.stdout.write(data.encode('hex'))
            else:
                sys.stdout.write(data)
            sys.stdout.flush()

    def _log_recv(self, data):
        if self.verbose and self.echo_recving:
            self._log_something(data, '<< ')
        if self.log_recv:
            self.log_recv.write(data)

    def _log_send(self, data):
        if self.verbose and self.echo_sending:
            self._log_something(data, '>> ')
        if self.log_send:
            self.log_send.write(data)

    @staticmethod
    def _print_lines(s, prefix):
        for line in s.split(b'\n'):
            print(prefix + str(line))

    @staticmethod
    def _print_hex_lines(s, prefix):
        for i in range(0, len(s), 16):
            sl = s[i:i+16]
            line = prefix + ' '.join('%02X' % ord(a) for a in sl)
            if i + 16 >= len(s):
                line += '   '*(16 - len(sl))

            line += '  |'
            for sc in sl:
                if sc == ' ' or (sc in string.printable and sc not in string.whitespace):
                    line += sc
                else:
                    line += '.'
            line += ' '*(16 - len(sl))
            line += '|'
            print(line)

    def settimeout(self, timeout):
        """
        Set the default timeout in seconds to use for subsequent socket operations
        """
        self._timeout = timeout
        self.sock.settimeout(timeout)
            
    def recv(self, n=4096, timeout='default'):
        """
        Receive at most n bytes (default 4096) from the socket
        """
        self.timed_out = False
            
        if self.verbose and self.echo_headers:
            if timeout:
                print('======== Receiving {0}B or until timeout ({1}) ========'.format(n, timeout))
            else:
                print('======== Receiving {0}B ========'.format(n))

        ret = b''
        if self.buf:
            ret = self.buf[:n]
            self.buf = self.buf[n:]
            self._log_recv(ret)
            return ret

        try:
            if timeout != 'default':
                self.sock.settimeout(timeout)

            self.buf += self.sock.recv(n - len(self.buf))
            ret = self.buf
            self.buf = b''
        except socket.timeout:
            self.timed_out = True
        except socket.error:
            raise NetcatError('Socket error!')

        self.sock.settimeout(self._timeout)

        if not timeout and ret == '':
            raise NetcatError("Connection dropped!")

        self._log_recv(ret)
        return ret

    def recv_until(self, s, timeout='default'):
        """
        Recieve data from the socket until the given substring is observed.
        Data in the same datagram as the substring, following the substring,
        will not be returned and will be cached for future receives.
        """
        self.timed_out = False
        if timeout == 'default':
            timeout = self._timeout
        
        if self.verbose and self.echo_headers:
            if timeout:
                print('======== Receiving until {0} or timeout ({1}) ========'.format(repr(s), timeout))
            else:
                print('======== Receiving until {0} ========'.format(repr(s)))

        start = time.time()
        try:
            while s not in self.buf:
                if timeout is not None:
                    dt = time.time()-start
                    if dt > timeout:
                        self.timed_out = True
                        break
                    self.sock.settimeout(timeout-dt)

                a = self.sock.recv(4096)
                if a == '':
                    raise NetcatError("Connection dropped!")
                
                self._log_recv(a)
                self.buf += a
        except socket.timeout:
            self.timed_out = True

        self.sock.settimeout(self._timeout)
        ret = self._head_buf(self.buf.index(s)+len(s) if not self.timed_out else None)
        self._log_recv(ret)
        return ret

    def recv_all(self, timeout='default'):
        """
        Return all data recieved until connection closes.
        """
        self.timed_out = False
        if timeout == 'default':
            timeout = self._timeout

        if self.verbose and self.echo_headers:
            if timeout:
                print('======== Receiving until close or timeout ({}) ========'.format(timeout))
            else:
                print('======== Receiving until close ========')

        start = time.time()
        try:
            while True:
                if timeout is not None:
                    dt = time.time()-start
                    if dt > timeout:
                        self.timed_out = True
                        break
                    self.sock.settimeout(timeout-dt)

                a = self.sock.recv(4096)
                if not a: break
                self.buf += a
                self._log_recv(a)

        except KeyboardInterrupt:
            if self.verbose and self.echo_headers:
                print('\n======== Connection interrupted! ========')
        except socket.timeout:
            self.timed_out = True
        except (socket.error, NetcatError):
            if self.verbose and self.echo_headers:
                print('\n======== Connection dropped! ========')

        self.sock.settimeout(self._timeout)
        ret = self.buf
        self.buf = b''
        return ret

    def recv_exactly(self, n, timeout='default'):
        """
        Recieve exactly n bytes
        """
        self.timed_out = False
        if timeout == 'default':
            timeout = self._timeout

        if self.verbose and self.echo_headers:
            if timeout:
                print('======== Receiving until exactly {0}B or timeout({})  ========'.format(n, timeout))
            else:
                print('======== Receiving until exactly {0}B  ========'.format(n))

        start = time.time()
        try:
            while len(self.buf) < n:
                if timeout is not None:
                    dt = time.time()-start
                    if dt > timeout:
                        self.timed_out = True
                        break
                    self.sock.settimeout(timeout-dt)

                a = self.sock.recv(n - len(self.buf))
                if len(a) == 0:
                    raise NetcatError("Connection closed before {0} bytes received!".format(n))
                self.buf += a
        except KeyboardInterrupt:
            if self.verbose and self.echo_headers:
                print('\n======== Connection interrupted! ========')
        except socket.timeout:
            self.timed_out = True
        except socket.error:
            raise NetcatError("Socket error!")

        out = self.buf[:n]
        self.buf = self.buf[n:]
        self._log_recv(out)
        return out

    def send(self, s):
        """
        Sends all the given data to the socket.
        """
        if self.verbose and self.echo_headers:
            print('======== Sending ({0}) ========'.format(len(s)))

        self._log_send(s)

        while s:
            if self.peer_implicit:
                s = s[self.sock.send(s):]
            else:
                s = s[self.sock.sendto(s, 0, self.peer):]

    def interact(self, insock=sys.stdin, outsock=sys.stdout):
        """
        Connects the socket to the terminal for user interaction.
        Alternate input and output files may be specified.

        This method cannot be used with a timeout.
        """
        if self.verbose and self.echo_headers:
            print('======== Beginning interactive session ========')

        self.timed_out = False

        save_verbose = self.verbose
        self.verbose = 0
        try:
            if self.buf:
                outsock.buffer.write(self.buf)
                outsock.flush()
                self._log_recv(self.buf)
                self.buf = b''
            dropped = False
            while not dropped:
                r, _, _ = select.select([self.sock, insock], [], [])
                for s in r:
                    if s == self.sock:
                        a = self.recv(timeout=None)
                        if a == b'':
                            dropped = True
                        else:
                            outsock.buffer.write(a)
                            outsock.flush()
                    else:
                        b = os.read(insock.fileno(), 4096)
                        self.send(b)
            raise NetcatError
        except KeyboardInterrupt:
            if save_verbose and self.echo_headers:
                print('\n======== Connection interrupted! ========')
        except (socket.error, NetcatError):
            if save_verbose and self.echo_headers:
                print('\n======== Connection dropped! ========')
        finally:
            self.verbose = save_verbose

    read = recv
    get = recv
    write = send
    put = send
    
    read_until = recv_until
    readuntil = recv_until
    recvuntil = recv_until
    
    read_all = recv_all
    readall = recv_all
    recvall = recv_all

    read_exactly = recv_exactly
    readexactly = recv_exactly
    recvexactly = recv_exactly
    
    interactive = interact
    ineraction = interact



