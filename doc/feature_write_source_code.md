# Writing source codes

sapcli allows writing source codes of ABAP objects. Users can either ask sapcli
to read the source codes from a file or read the source code from standard
input.

sapcli usually defines the argument `source` which can either hold file path or
'-' for reading from STDIN.

The MCP server cannot use STDIN because of its nature (an HTTP server running
somewhere not directly in the current working directory of the
project).

The MCP server can accept an absolute file path but it is more likely the path
will not be accessible because the MCP sever will likely run in a docker
container or on a remote machine.

## Handling of the argument source

The MCP tool from ArgParser generator must detect the argument source and
change the definition to say that the value is either the actual source code or
an absolute path in the case the MCP server is running locally.

To avoid any unexpected behaviour such as accidental overwriting object by a
file path (imagine if the source code would actually be a file path), the tool
generator must automatically create 2 tool parameters:
- source\_data
- source\_file\_path

Idea 1: perhaps it would be better to create 2 tools - abap_obj_write_data and
abap_obj_write_from_file.

Idea 2: perhaps it would be easier to enforce use of the data based parameter
in the first version.

Both parameters must be optional and exactly one must be passed.

In the case source_file_path is given, the tool checks access and if the file
is not present, the tool must let the client know that file paths are tricky if
the MCP server is not running locally or running in a container (the user would
have to somehow mount the host's file system into the container).

In the case source\_data are given, the data are written into a temporary file
and the path is used instead. (sapcli reads directly from sys.stdin and adding
an abstraction for that is currently an overkill).

