#!/usr/bin/env python3
"""Measure three runs of 300 LSP-like progress redraws; optionally pass an Nvim binary."""
import os, pty, fcntl, termios, struct, select, subprocess, time, tempfile, json, sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='smooth-redraw-') as d:
 pth=Path(d)
 (pth/'bench.lua').write_text('''local lines={} for i=1,500 do lines[i]=('line %04d '):format(i)..string.rep('startup highlighting text ',8) end
vim.api.nvim_buf_set_lines(0,0,-1,false,lines)
local buf=vim.api.nvim_create_buf(false,true)
local win=vim.api.nvim_open_win(buf,false,{relative='editor',row=2,col=120,width=40,height=2,style='minimal'})
vim.defer_fn(function()
 local results={}
 for round=1,3 do
  local start=vim.uv.hrtime()
  for i=1,300 do
   vim.api.nvim_buf_set_lines(buf,0,-1,false,{'LSP startup progress '..i})
   if i%20==0 then vim.cmd('normal! j') end
   vim.cmd('redraw')
  end
  results[#results+1]=(vim.uv.hrtime()-start)/1e6
 end
 vim.fn.writefile({vim.json.encode(results)},vim.env.SMOOTH_RESULTS)
 vim.cmd('qa!')
end,100)
''')
 m,s=pty.openpty(); fcntl.ioctl(s,termios.TIOCSWINSZ,struct.pack('HHHH',70,200,0,0))
 env=dict(os.environ,TERM='xterm-kitty',VIMRUNTIME=str(root/'runtime'),NVIM_KITTY_SMOOTH='1',XDG_STATE_HOME=str(pth/'state'),XDG_CACHE_HOME=str(pth/'cache'),SMOOTH_RESULTS=str(pth/'result'))
 proc=subprocess.Popen([(sys.argv[1] if len(sys.argv) > 1 else str(root/'build-smooth/bin/nvim')),'-u','NONE','-n','-i','NONE','-c',f'luafile {pth}/bench.lua'],stdin=s,stdout=s,stderr=s,env=env,start_new_session=True);os.close(s)
 data=b'';replied=False
 try:
  deadline=time.monotonic()+30
  while time.monotonic()<deadline:
   if select.select([m],[],[],.1)[0]:
    try: chunk=os.read(m,262144)
    except OSError: break
    data+=chunk
    if not replied and b'\x1b[?2026$p' in data:
     os.write(m,b'\x1b[?2026;1$y');replied=True
   if proc.poll() is not None: break
  proc.wait(timeout=2)
  assert proc.returncode==0,data[-1500:]
  print(json.loads((pth/'result').read_text()))
 finally:
  if proc.poll() is None: proc.kill();proc.wait()
  os.close(m)
