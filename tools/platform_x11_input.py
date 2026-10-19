"""XTest input for one already-created private Xvfb display. No simulation access.

Libraries are opened only when the native owner explicitly constructs Input.
The caller owns Xauthority/server lifetime. Never connect to the user's display.
"""
import ctypes as C
import ctypes.util

class Input:
    def __init__(self,display):
        if not display.startswith(':'):raise ValueError('local private X display required')
        self.x=C.CDLL(ctypes.util.find_library('X11'));self.xt=C.CDLL(ctypes.util.find_library('Xtst'))
        self.x.XOpenDisplay.argtypes=[C.c_char_p];self.x.XOpenDisplay.restype=C.c_void_p
        self.x.XDefaultRootWindow.argtypes=[C.c_void_p];self.x.XDefaultRootWindow.restype=C.c_ulong
        self.x.XQueryTree.argtypes=[C.c_void_p,C.c_ulong,C.POINTER(C.c_ulong),C.POINTER(C.c_ulong),C.POINTER(C.POINTER(C.c_ulong)),C.POINTER(C.c_uint)]
        self.x.XFetchName.argtypes=[C.c_void_p,C.c_ulong,C.POINTER(C.c_char_p)]
        self.x.XFree.argtypes=[C.c_void_p];self.x.XStringToKeysym.argtypes=[C.c_char_p];self.x.XStringToKeysym.restype=C.c_ulong
        self.x.XKeysymToKeycode.argtypes=[C.c_void_p,C.c_ulong];self.x.XKeysymToKeycode.restype=C.c_ubyte
        self.x.XSetInputFocus.argtypes=[C.c_void_p,C.c_ulong,C.c_int,C.c_ulong]
        self.x.XRaiseWindow.argtypes=[C.c_void_p,C.c_ulong];self.x.XFlush.argtypes=[C.c_void_p]
        self.x.XCloseDisplay.argtypes=[C.c_void_p]
        self.xt.XTestFakeKeyEvent.argtypes=[C.c_void_p,C.c_uint,C.c_int,C.c_ulong]
        self.xt.XTestFakeRelativeMotionEvent.argtypes=[C.c_void_p,C.c_int,C.c_int,C.c_ulong]
        self.xt.XTestFakeButtonEvent.argtypes=[C.c_void_p,C.c_uint,C.c_int,C.c_ulong]
        self.d=self.x.XOpenDisplay(display.encode());self.held=set();self.buttons=set()
        if not self.d:raise RuntimeError('private X display could not be opened')
    def windows(self):
        found=[]
        def scan(window,depth=0):
            name=C.c_char_p()
            if self.x.XFetchName(self.d,window,C.byref(name)) and name:
                text=name.value.decode('utf-8','replace');self.x.XFree(name)
                if text.startswith('RUST DUTY'):found.append(window)
            if depth>=4:return
            root=C.c_ulong();parent=C.c_ulong();children=C.POINTER(C.c_ulong)();n=C.c_uint()
            if self.x.XQueryTree(self.d,window,C.byref(root),C.byref(parent),C.byref(children),C.byref(n)):
                values=[children[i] for i in range(n.value)]
                if children:self.x.XFree(children)
                for child in values:scan(child,depth+1)
        scan(self.x.XDefaultRootWindow(self.d));return found
    def focus(self,window):
        self.x.XRaiseWindow(self.d,window);self.x.XSetInputFocus(self.d,window,1,0);self.x.XFlush(self.d)
    def key(self,name,down):
        if name not in {'w','a','s','d','space','Return','Escape','F2','F9','F10'}:raise ValueError('unapproved fixture key')
        code=self.x.XKeysymToKeycode(self.d,self.x.XStringToKeysym(name.encode()))
        if not code or not self.xt.XTestFakeKeyEvent(self.d,code,bool(down),0):raise RuntimeError('native key injection failed')
        (self.held.add if down else self.held.discard)(name);self.x.XFlush(self.d)
    def ads(self,down):
        if not self.xt.XTestFakeButtonEvent(self.d,3,bool(down),0):raise RuntimeError('native ADS input failed')
        (self.buttons.add if down else self.buttons.discard)(3);self.x.XFlush(self.d)
    def look(self,dx):
        if type(dx) is not int or abs(dx)>120:raise ValueError('bounded native look delta required')
        if not self.xt.XTestFakeRelativeMotionEvent(self.d,dx,0,0):raise RuntimeError('native look event failed')
        self.x.XFlush(self.d)
    def release(self):
        for name in list(self.held):self.key(name,False)
        if self.buttons:self.ads(False)
    def close(self):
        self.release();self.x.XCloseDisplay(self.d);self.d=None
