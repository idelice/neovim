#!/usr/bin/env python3
"""PTY regression for smooth frame cursor style; requires build-smooth."""
import fcntl
import os
from pathlib import Path
import pty
import re
import select
import signal
import struct
import subprocess
import tempfile
import termios
import time

root = Path(__file__).resolve().parents[1]
LUA = r'''
local function mark(s) vim.api.nvim_ui_send('\27]777;'..s..'\27\\') end
vim.defer_fn(function()
 vim.api.nvim_ui_send('\27[1 q')
 vim.cmd('enew');vim.api.nvim_buf_set_lines(0,0,-1,false,{'definition'})
 vim.cmd('redraw!')
 vim.defer_fn(function()
 mark('STEADY')
 vim.o.guicursor='a:block-blinkon300-blinkoff300'
 vim.cmd('redraw!')
 vim.defer_fn(function()
 mark('BLINK')
 vim.o.guicursor='a:block-blinkon0'
 vim.cmd('buffer #');vim.cmd('redraw!')
 vim.defer_fn(function() mark('RETURN');vim.cmd('qa!') end,200)
 end,200)
 end,200)
end,200)
'''

with tempfile.TemporaryDirectory(prefix='smooth-cursor-') as temporary:
    script = Path(temporary) / 'test.lua'
    script.write_text(LUA)
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 30, 100, 0, 0))
    env = dict(os.environ, TERM='xterm-kitty', VIMRUNTIME=str(root / 'runtime'),
               NVIM_KITTY_SMOOTH='1', NVIM_LOG_FILE=str(Path(temporary) / 'nvim.log'))
    process = subprocess.Popen(
        [str(root / 'build-smooth/bin/nvim'), '-u', 'NONE', '-n', '-i', 'NONE',
         '-c', "lua dofile(" + repr(str(script)) + ")"],
        stdin=slave, stdout=slave, stderr=slave, env=env, start_new_session=True)
    os.close(slave)
    data = b''
    replied = False
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if select.select([master], [], [], .1)[0]:
                try:
                    data += os.read(master, 262144)
                except OSError:
                    break
                if not replied and b'\x1b[?2026$p' in data:
                    os.write(master, b'\x1b[?2026;1$y')
                    replied = True
            if process.poll() is not None:
                break
        process.wait(timeout=2)
        assert process.returncode == 0, data[-2000:]
    finally:
        os.close(master)
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()

for marker, expected in ((b'STEADY', b'2'), (b'BLINK', b'1'), (b'RETURN', b'2')):
    boundary = b'\x1b]777;' + marker + b'\x1b\\'
    assert boundary in data, ('Missing phase', marker)
    styles = re.findall(rb'\x1b\[([0-6]) q', data.split(boundary)[0])
    assert styles and styles[-1] == expected, (marker, styles)
print('PASS: steady cursor restored after transient reset; explicit blinking preserved; return jump steady')
