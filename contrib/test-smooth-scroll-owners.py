#!/usr/bin/env python3
"""PTY regression for source-owned pane/float scroll notifications."""
import os,pty,subprocess,fcntl,termios,struct,select,time,re
from pathlib import Path
root=str(Path(__file__).resolve().parents[1])
actions='''vim.api.nvim_buf_set_lines(0,0,-1,false,vim.fn.readfile(vim.env.VIMRUNTIME..'/doc/api.txt')); local a=vim.api.nvim_get_current_win(); vim.cmd('vsplit'); local b=vim.api.nvim_get_current_win(); local buf=vim.api.nvim_create_buf(false,true); vim.api.nvim_buf_set_lines(buf,0,-1,false,vim.fn.readfile(vim.env.VIMRUNTIME..'/doc/api.txt')); local c=vim.api.nvim_open_win(buf,false,{relative='editor',row=3,col=2,width=25,height=12}); vim.defer_fn(function() for _,w in ipairs({a,b,c}) do vim.api.nvim_win_call(w,function() vim.cmd('normal! 5\\5') end) end; vim.defer_fn(function() vim.cmd('qa!') end,200) end,300)'''
open('/tmp/smooth-owner-actions.lua','w').write(actions)
def capture(enabled):
 m,s=pty.openpty();fcntl.ioctl(s,termios.TIOCSWINSZ,struct.pack('HHHH',30,100,0,0));env=dict(os.environ,TERM='xterm-kitty',VIMRUNTIME=root+'/runtime',XDG_STATE_HOME='/tmp/nvim-smooth-test-state');env.pop('NVIM_KITTY_SMOOTH',None)
 if enabled:env['NVIM_KITTY_SMOOTH']='1'
 p=subprocess.Popen([root+'/build-smooth/bin/nvim','-u','NONE','-n','-i','NONE','-c','luafile /tmp/smooth-owner-actions.lua'],stdin=s,stdout=s,stderr=s,env=env);os.close(s);out=b'';end=time.monotonic()+8
 while time.monotonic()<end:
  if select.select([m],[],[],.1)[0]:
   try:chunk=os.read(m,65536)
   except OSError:break
   out+=chunk
  if p.poll()!=None:break
 p.wait(timeout=2);os.close(m);assert p.returncode==0
 return out
on=capture(True);off=capture(False)
packets=re.findall(rb'\x1b\]9923;(-?\d+);(\d+);(\d+);(\d+);(\d+);(-?\d+)\x1b\\',on)
assert len(set(x[0] for x in packets))==3,packets
assert b']9911;' not in on
assert b']9923;' not in off
print('PASS: two panes plus overlapping float emit independent stable owners, no duplicate or non-opt-in packets:',packets)
open('/tmp/smooth-owner-stream.bin','wb').write(on)
