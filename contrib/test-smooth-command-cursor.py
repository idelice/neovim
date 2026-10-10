#!/usr/bin/env python3
"""Cursor ownership regression; requires installed Noice and nui.nvim."""
import os,pty,subprocess,fcntl,termios,struct,select,time,re
from pathlib import Path
root=Path(__file__).resolve().parents[1]
script=Path('/tmp/smooth-command-cursor.lua')
script.write_text('''for _,p in ipairs({'nui.nvim','noice.nvim'}) do vim.opt.rtp:prepend(vim.fn.stdpath('data')..'/lazy/'..p) end
require('noice').setup({})
vim.defer_fn(function() vim.api.nvim_input(':') end,200)
vim.defer_fn(function() vim.api.nvim_ui_send('\\27]9990;cmdline\\27\\\\') end,900)
vim.defer_fn(function() vim.api.nvim_input('\\27'); vim.schedule(function() vim.cmd('qa!') end) end,1200)
''')
m,s=pty.openpty();fcntl.ioctl(s,termios.TIOCSWINSZ,struct.pack('HHHH',30,100,0,0))
env=dict(os.environ,TERM='xterm-kitty',VIMRUNTIME=str(root/'runtime'),NVIM_KITTY_SMOOTH='1',XDG_STATE_HOME='/tmp/nvim-smooth-state')
p=subprocess.Popen([str(root/'build-smooth/bin/nvim'),'-u','NONE','-n','-i','NONE','-c',f'luafile {script}'],stdin=s,stdout=s,stderr=s,env=env);os.close(s)
out=b''
try:
 end=time.monotonic()+8
 while time.monotonic()<end:
  if select.select([m],[],[],.1)[0]:
   try: out+=os.read(m,262144)
   except OSError: break
  if p.poll() is not None: break
 p.wait(timeout=1)
finally:
 if p.poll() is None:
  p.terminate()
  try:p.wait(timeout=2)
  except subprocess.TimeoutExpired:p.kill();p.wait()
 os.close(m)
assert p.returncode==0,out[-2000:]
Path('/tmp/smooth-command-cursor.bin').write_bytes(out)
raw=out.split(b'\x1b]9990;cmdline')[0]
frames=re.findall(rb'\x1b\]9918;\x1b\\(.*?)\x1b\]9920;\x1b\\',raw,re.S)
assert frames
frame=frames[-1]
owner=int(re.search(rb'\x1b\]9924;(-?\d+)',frame)[1])
windows=[tuple(map(int,x)) for x in re.findall(rb'\x1b\]9919;(-?\d+);(\d+);(\d+);(\d+);(\d+);(\d+);',frame)]
assert any(w[0]==owner and w[5]>0 for w in windows),(owner,windows)
print('PASS: non-current Noice command input owns native cursor',owner)
