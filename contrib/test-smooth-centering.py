#!/usr/bin/env python3
"""Bounded clean-config PTY regression for repeated zz and startup redraw churn."""
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
with tempfile.TemporaryDirectory(prefix='smooth-centering-') as directory:
    directory = Path(directory)
    script = directory / 'actions.lua'
    script.write_text(r'''
local lines = {}
for i=1,500 do lines[i] = ('line %04d'):format(i) end
vim.api.nvim_buf_set_lines(0,0,-1,false,lines)
vim.wo.wrap=false
vim.wo.scrolloff=0
vim.cmd('normal! 100G')
vim.cmd('redraw!')
local expected={}
local step=0
local function tick()
  step=step+1
  if step>12 then
    vim.fn.writefile(expected, vim.env.SMOOTH_RESULTS)
    vim.cmd('qa!')
    return
  end
  vim.api.nvim_win_set_cursor(0,{100+step*3,0})
  vim.cmd('redraw')
  local before=vim.fn.winsaveview().topline
  vim.api.nvim_ui_send(('\27]9930;BEGIN;%d\27\\'):format(step))
  vim.cmd('normal! zz')
  vim.cmd('redraw')
  local after=vim.fn.winsaveview().topline
  vim.api.nvim_ui_send(('\27]9930;END;%d\27\\'):format(step))
  vim.cmd('redraw')
  expected[#expected+1]=('%d %d'):format(step,after-before)
  -- Mimic asynchronous startup highlighting between navigation redraws.
  vim.api.nvim_set_hl(0,'Normal',{fg=step%2==0 and '#dddddd' or '#eeeeee'})
  vim.cmd('redraw')
  vim.defer_fn(tick,20)
end
vim.defer_fn(tick,80)
''')
    env = dict(os.environ, TERM='xterm-kitty', VIMRUNTIME=str(root / 'runtime'),
               NVIM_KITTY_SMOOTH='1', SMOOTH_RESULTS=str(directory / 'results'),
               XDG_STATE_HOME=str(directory / 'state'), XDG_CACHE_HOME=str(directory / 'cache'),
               NVIM_LOG_FILE=str(directory / 'nvim.log'))
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH',30,100,0,0))
    process = subprocess.Popen([str(root / 'build-smooth/bin/nvim'), '-u','NONE','-n','-i','NONE',
        '-c', f'luafile {script}'], stdin=slave, stdout=slave, stderr=slave, env=env, start_new_session=True)
    os.close(slave)
    output = b''
    replied = False
    try:
        deadline = time.monotonic()+8
        while time.monotonic()<deadline:
            if select.select([master],[],[],.05)[0]:
                try:
                    output += os.read(master,262144)
                except OSError:
                    break
                if not replied and b'\x1b[?2026$p' in output:
                    os.write(master,b'\x1b[?2026;1$y')
                    replied=True
            if process.poll() is not None:
                break
        process.wait(timeout=2)
        assert process.returncode == 0, output[-2000:]
        expected = [tuple(map(int,line.split())) for line in (directory / 'results').read_text().splitlines()]
        for step, delta in expected:
            frame = re.search(rb'\x1b\]9930;BEGIN;'+str(step).encode()+rb'\x1b\\(.*?)\x1b\]9930;END;'+str(step).encode()+rb'\x1b\\',output,re.S)
            assert frame, (step,output[-1000:])
            deltas = re.findall(rb'\x1b\]9923;[^\x1b]*;(-?\d+)\x1b\\',frame[1])
            assert sum(map(int,deltas)) == delta, (step,delta,deltas)
        print('PASS: 12 repeated zz frames preserve exact viewport displacement during startup highlight churn')
    finally:
        if process.poll() is None:
            os.killpg(process.pid,signal.SIGTERM)
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid,signal.SIGKILL)
                process.wait()
        os.close(master)
