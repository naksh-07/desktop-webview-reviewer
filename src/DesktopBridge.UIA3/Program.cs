using System;
using System.IO;
using System.IO.Pipes;
using System.Text;
using System.Threading;

namespace DesktopBridge.UIA3
{
    public class Program
    {
        public const string ProtocolVersion = "1.0";
        public const string SidecarVersion = "1.0.0";

        [MTAThread]
        public static int Main(string[] args)
        {
            string pipeName = null;
            bool stdioMode = false;

            for (int i = 0; i < args.Length; i++)
            {
                if (args[i] == "--pipe" && i + 1 < args.Length)
                {
                    pipeName = args[i + 1];
                    i++;
                }
                else if (args[i] == "--stdio")
                {
                    stdioMode = true;
                }
            }

            if (!string.IsNullOrEmpty(pipeName))
            {
                RunNamedPipeServer(pipeName);
                return 0;
            }

            if (stdioMode || args.Length == 0)
            {
                RunStdioServer();
                return 0;
            }

            Console.WriteLine("Usage: DesktopBridge.UIA3.exe [--pipe <pipename>] [--stdio]");
            return 1;
        }

        private static void RunNamedPipeServer(string pipeName)
        {
            Console.WriteLine("[Sidecar] Starting Named Pipe server: " + pipeName + " [MTAThread]");
            using (NamedPipeServerStream server = new NamedPipeServerStream(pipeName, PipeDirection.InOut, 1, PipeTransmissionMode.Byte, PipeOptions.Asynchronous))
            {
                server.WaitForConnection();
                Console.WriteLine("[Sidecar] Client connected to pipe: " + pipeName);

                using (StreamReader reader = new StreamReader(server, Encoding.UTF8))
                using (StreamWriter writer = new StreamWriter(server, Encoding.UTF8) { AutoFlush = true })
                {
                    string line;
                    bool shouldExit;
                    while ((line = reader.ReadLine()) != null)
                    {
                        string responseJson = ProcessRequest(line, out shouldExit);
                        writer.WriteLine(responseJson);
                        if (shouldExit)
                        {
                            break;
                        }
                    }
                }
            }
            Console.WriteLine("[Sidecar] Named pipe server exiting cleanly.");
        }

        private static void RunStdioServer()
        {
            Console.Error.WriteLine("[Sidecar] Running in stdio mode [MTAThread]");
            string line;
            bool shouldExit;
            while ((line = Console.ReadLine()) != null)
            {
                string responseJson = ProcessRequest(line, out shouldExit);
                Console.WriteLine(responseJson);
                if (shouldExit)
                {
                    break;
                }
            }
            Console.Error.WriteLine("[Sidecar] Stdio server exiting cleanly.");
        }

        private static string ProcessRequest(string rawJson, out bool shouldExit)
        {
            shouldExit = false;
            string id = "null";
            string method = "";

            try
            {
                id = ExtractJsonField(rawJson, "id") ?? "null";
                method = ExtractJsonField(rawJson, "method") ?? "";

                if (method == "handshake")
                {
                    return "{\"jsonrpc\":\"2.0\",\"id\":" + FormatJsonId(id) + ",\"result\":{" +
                           "\"protocol_version\":\"" + ProtocolVersion + "\"," +
                           "\"sidecar_version\":\"" + SidecarVersion + "\"," +
                           "\"status\":\"READY\"," +
                           "\"apartment_state\":\"MTA\"" +
                           "}}";
                }
                else if (method == "ping")
                {
                    return "{\"jsonrpc\":\"2.0\",\"id\":" + FormatJsonId(id) + ",\"result\":{\"pong\":true}}";
                }
                else if (method == "health")
                {
                    long mem = GC.GetTotalMemory(false);
                    return "{\"jsonrpc\":\"2.0\",\"id\":" + FormatJsonId(id) + ",\"result\":{" +
                           "\"status\":\"HEALTHY\"," +
                           "\"memory_bytes\":" + mem +
                           "}}";
                }
                else if (method == "shutdown")
                {
                    shouldExit = true;
                    return "{\"jsonrpc\":\"2.0\",\"id\":" + FormatJsonId(id) + ",\"result\":{\"acknowledged\":true}}";
                }
                else
                {
                    return "{\"jsonrpc\":\"2.0\",\"id\":" + FormatJsonId(id) + ",\"error\":{\"code\":-32601,\"message\":\"Method not found: " + method + "\"}}";
                }
            }
            catch (Exception ex)
            {
                return "{\"jsonrpc\":\"2.0\",\"id\":" + FormatJsonId(id) + ",\"error\":{\"code\":-32603,\"message\":\"Internal error: " + ex.Message + "\"}}";
            }
        }

        private static string ExtractJsonField(string json, string field)
        {
            string pattern = "\"" + field + "\"";
            int idx = json.IndexOf(pattern);
            if (idx == -1) return null;

            int colonIdx = json.IndexOf(':', idx + pattern.Length);
            if (colonIdx == -1) return null;

            int start = colonIdx + 1;
            while (start < json.Length && char.IsWhiteSpace(json[start])) start++;

            if (start >= json.Length) return null;

            if (json[start] == '\"')
            {
                int end = json.IndexOf('\"', start + 1);
                return (end != -1) ? json.Substring(start + 1, end - start - 1) : null;
            }
            else
            {
                int end = start;
                while (end < json.Length && json[end] != ',' && json[end] != '}' && !char.IsWhiteSpace(json[end])) end++;
                return json.Substring(start, end - start);
            }
        }

        private static string FormatJsonId(string id)
        {
            long dummy;
            if (id == "null" || long.TryParse(id, out dummy))
            {
                return id;
            }
            return "\"" + id + "\"";
        }
    }
}
