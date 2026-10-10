#!/usr/bin/env python3
"""PTY regression for the opt-in native retained-grid bridge; requires build-smooth."""
import os,pty,subprocess,fcntl,termios,struct,select,time,re
from pathlib import Path
root=Path(__file__).resolve().parents[1]
script=r'''
dofile('/Users/delice/projects/neovim/contrib/smooth-nvim.lua')
local base=vim.api.nvim_get_current_buf()
local lines={}
for i=1,28 do lines[i]=string.rep(' ',12)..'UNDERLAY_'..i end
vim.api.nvim_buf_set_lines(base,0,-1,false,lines)
vim.wo.number=false;vim.wo.relativenumber=false;vim.wo.signcolumn='no'
vim.defer_fn(function()
 local a=vim.api.nvim_create_buf(false,true)
 vim.api.nvim_buf_set_lines(a,0,-1,false,{'FLOAT_A_OLD','FLOAT_A_SECOND'})
 local wa=vim.api.nvim_open_win(a,true,{relative='editor',row=3,col=10,width=25,height=8,border='rounded',zindex=1001})
 vim.defer_fn(function()
  local b=vim.api.nvim_create_buf(false,true)
  vim.api.nvim_buf_set_lines(b,0,-1,false,{'FLOAT_B_TOP'})
  local wb=vim.api.nvim_open_win(b,true,{relative='editor',row=4,col=12,width=20,height=5,border='single',zindex=1000000})
  vim.defer_fn(function()
   local replacement=vim.api.nvim_create_buf(false,true)
   vim.api.nvim_buf_set_lines(replacement,0,-1,false,{'FLOAT_A_REPLACED'})
   vim.api.nvim_win_set_buf(wa,replacement)
   vim.api.nvim_win_set_config(wa,{relative='editor',row=6,col=30,width=29,height=9})
   vim.defer_fn(function()
    vim.api.nvim_win_close(wb,true)
    vim.defer_fn(function()
     vim.api.nvim_win_close(wa,true)
     vim.defer_fn(function()
      vim.api.nvim_win_set_cursor(0,{1,0})
      vim.cmd('startinsert')
      vim.defer_fn(function()
       vim.fn.complete(1,{'COMPLETION_ALPHA','COMPLETION_BETA'})
       vim.defer_fn(function() vim.cmd('qa!') end,180)
      end,60)
     end,180)
    end,180)
   end,180)
  end,180)
 end,180)
end,180)
'''
script=script.replace('/Users/delice/projects/neovim',str(root))
Path('/tmp/native-grid-actions.lua').write_text(script)
m,s=pty.openpty();fcntl.ioctl(s,termios.TIOCSWINSZ,struct.pack('HHHH',30,100,0,0))
env=dict(os.environ,TERM='xterm-kitty',VIMRUNTIME=str(root/'runtime'),NVIM_KITTY_SMOOTH='1',NVIM_LOG_FILE='/tmp/native-grid-test.log',XDG_STATE_HOME='/tmp/native-grid-state',XDG_CACHE_HOME='/tmp/native-grid-cache')
p=subprocess.Popen([str(root/'build-smooth/bin/nvim'),'-u','NONE','-n','-i','NONE','-c',"lua dofile('/tmp/native-grid-actions.lua')"],stdin=s,stdout=s,stderr=s,env=env);os.close(s)
data=b'';replied=False;end=time.monotonic()+10
while time.monotonic()<end:
 if select.select([m],[],[],.1)[0]:
  try:
   data+=os.read(m,262144)
   if not replied and b'\x1b[?2026$p' in data:
    os.write(m,b'\x1b[?2026;1$y');replied=True
  except OSError:break
 if p.poll() is not None:break
p.wait(timeout=2);os.close(m)
assert p.returncode==0,data[-2500:]
Path('/tmp/native-grid-stream.bin').write_bytes(data)
assert b'\x1b]9921;' in data,'No native retained grid layers'
assert b'FLOAT_A_REPLACED' in data and b'FLOAT_B_TOP' in data
print('PASS: generic filetype-free overlapping floats, replacement and motion exported native retained layers:',len(data),'bytes')

from pathlib import Path
import re
raw=Path('/tmp/native-grid-stream.bin').read_bytes()
blocks=[]
for m in re.finditer(rb'\x1b\]9921;(-?\d+);(\d+);(\d+);(\d+);(\d+);(\d+)\x1b\\(.*?)\x1b\]9922;\x1b\\',raw,re.S):
 fields=tuple(map(int,m.groups()[:6]));text=re.sub(rb'\x1b\[[0-9:;?]*[A-Za-z]',b'',m.group(7))
 blocks.append((fields,text))
base=[text for fields,text in blocks if fields[0]==1]
a=[(fields,text) for fields,text in blocks if b'FLOAT_A_' in text]
b=[(fields,text) for fields,text in blocks if b'FLOAT_B_TOP' in text]
assert base and a and b
assert all(b'FLOAT_A_' not in text and b'FLOAT_B_TOP' not in text for text in base)
assert any(b'UNDERLAY_5' in text for text in base)
assert len({fields[0] for fields,text in a})==1,'Buffer replacement changed layer identity'
assert any(b'FLOAT_A_REPLACED' in text for fields,text in a)
assert a[0][0][1:3] != a[-1][0][1:3], 'Window movement did not export updated geometry'
assert 0 < a[0][0][5] < b[0][0][5] <= 1000000, 'High z-index floats lost compositor stacking order'
popup=[fields for fields,text in blocks if fields[0] < 0 and b'COMPLETION_ALPHA' in text and b'COMPLETION_BETA' in text]
assert popup and all(0 < fields[5] <= 1000000 for fields in popup), 'Native completion menu was not exported'
frames=re.findall(rb'\x1b\]9918;\x1b\\(.*?)\x1b\]9920;\x1b\\',raw,re.S)
assert frames
last=frames[-1]
assert str(a[0][0][0]).encode() not in re.findall(rb'\x1b\]9919;(-?\d+);',last),'Closed window still in final inventory'
print('PASS: native independent underlay, stable buffer replacement identity, movement, overlap and close inventory')
print('PASS: arbitrary high-z-index floats retain bounded stacking priority and native completion menu exports')
