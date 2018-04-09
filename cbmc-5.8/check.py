#!/usr/bin/python3
import sys
import os
import re
import signal
import hashlib
import subprocess
from timeit import Timer
from distutils.spawn import find_executable

result_path = "cbmc-output.txt"

base = os.path.join( os.path.dirname( os.path.realpath(__file__) ), "cbmc" )
cbmc = os.path.join( base, "cbmc-binary" )
cbmc_svc = os.path.join( base, "cbmc" )

class BenchDescription:
    def __init__( self, driver_checsum, driver, version, checksum, build ):
        self.driver_checsum = driver_checsum
        self.driver = driver
        self.version = version
        self.checksum = checksum
        self.build = build

    def __str__( self ):
        str =  "driver checksum: {}\n".format(self.driver_checsum)
        str += "driver: {}\n".format(self.driver)
        str += "version: {}\n".format(self.version)
        str += "checksum: {}\n".format(self.checksum)
        str += "build type: {}\n".format(self.build)
        return str

def sha1_bin( name ):
    path = find_executable( name )
    with open(path, "rb") as h:
        binary = h.read()
        return hashlib.sha1(binary).hexdigest();

def description():
    path = os.path.realpath(__file__).encode('utf-8')
    driver_checsum = sha1_bin( path )
    driver = cbmc + "/" + os.path.basename(__file__)
    proc = subprocess.Popen( [cbmc, "--version"], stdout = subprocess.PIPE )
    version = proc.stdout.readline().rstrip().decode('utf-8')
    proc.wait()
    checksum = sha1_bin( cbmc )
    build_type = "Release"
    return BenchDescription( driver_checsum, driver, version, checksum, build_type )

cc_args = []
bc_arg = ""
file_args = []

def cc( args ):
    print( args, file=sys.stderr )
    global cc_args, bc_arg, file_args
    i = 0
    end = len( args )
    while i != end:
        a = args[i]
        if a.endswith( ".c" ) or a.endswith( ".cpp" ) or a.endswith( ".cc" ):
            file_args.append( a )
        elif a == '-o':
            i += 1
            assert bc_arg == ""
            bc_arg += args[i]
        elif a == '-fgnu89-inline':
            pass
        else:
            cc_args.append( a )
        i += 1

def bench(args, time):
    with open( result_path, "w" ) as out:
        proc = subprocess.Popen( args, stdout = out, stderr = subprocess.STDOUT, shell = False, encoding='utf-8' )
        try:
            returncode = proc.wait( timeout = time )
            print( "EC:", returncode, file = out )
        except subprocess.TimeoutExpired:
            print("timeout: 1")
            print( "W: timeout", file=sys.stderr )
            proc.kill()

def set_cgs( cg, max_mem, controls ):
    for control in controls:
        f = os.path.join( cg, control )
        try:
            with open( f, "w" ) as h:
                if max_mem is not None:
                    h.write( str( max_mem ) )
                else:
                    h.write( "1E" )
        except PermissionError:
            print( "W: memory limit setting failed", file = sys.stderr )

def set_max_mem( max_mem ):
    pid = os.getpid()
    proccg = os.path.join( "/proc", str( pid ), "cgroup" )
    cg = None
    with open( proccg ) as hpcg:
        regex = re.compile( r':memory:(.*)$' )
        for line in hpcg:
            m = regex.search( line )
            if m:
                cg = os.path.join( "/sys/fs/cgroup/memory", m.group(1)[1:] )
    assert cg is not None

    # sadly, the order in which limits should be set depends on the current
    # value of limits, so try both orders if necessary
    controls = [ "memory.memsw.limit_in_bytes", "memory.limit_in_bytes" ]
    try:
        set_cgs( cg, max_mem, controls )
    except OSError:
        set_cgs( cg, max_mem, reversed( controls ) )

def get_limit( envvar ):
    v = os.getenv( envvar )
    if v:
        return int( v )
    return None

def run( args, expect ):
    idx = 0
    max_time = get_limit( "DIVBENCH_MAX_TIME" )
    max_mem = get_limit( "DIVBENCH_MAX_MEM" )
    sargs = []
    while idx < len(args):
        if args[idx] == '-o': idx += 2
        elif args[idx] == '--max-time':
            max_time = int(args[idx+1])
            idx += 2
        elif args[idx] == '--max-memory':
            max_mem = args[idx + 1]
            idx += 2
        elif args[idx] == '--symbolic': idx += 1
        elif args[idx] == '--sequential': idx += 1
        elif args[idx] == '--svcomp': idx += 1
        elif args[idx].endswith( '.bc' ): idx += 1
        else:
            sargs.append(args[idx])
            idx += 1

    set_max_mem( max_mem )

    cmd = [cbmc] + cc_args + sargs + file_args;

    print( cmd, file=sys.stderr )
#    print( expect, file=sys.stderr )
    timer = Timer(lambda: bench( cmd, max_time ))

    time = timer.timeit(number = 1)
    print("timers:")
    print("  search: {0:.3f}".format(time))

    lines = [line for line in open(result_path).read().splitlines()]
    try:
#        print("state count: 0")
        print("error found: ", end="")
        actual = None
        if ( "Usage error!" in lines ):
            raise ValueError
        if ( "EC: 10" in lines ):
            print( "yes" )
            actual = "error"
        elif ( "EC: 0" in lines ):
            print( "no" )
            actual = "valid"
        else:
            print( "null" )
        if expect is not None and actual != expect: print("wrong: 1")
    except ValueError:
        print("Warning! Unexpected output", file=sys.stderr)
        for l in lines: print(l, file=sys.stderr)

def main():
    if ( len(sys.argv) == 1 ):
        desc = description()
        print( desc )
    else:
        expect = None
        for line in open( sys.argv[1] ):
            tok = line.split();
            if tok[0] == 'cc': cc( tok[1:] )
            elif tok[0] == 'verify': run( tok[1:], expect )
            elif tok[0] == 'expect':
                if tok[1] == "--result": expect = tok[2]
                else: print( "W: unexpected option to expect: " + tok[1], file=sys.stderr )
            else: print( "W: unexpected script line: " + line, file=sys.stderr )

if __name__ == "__main__":
    main()
