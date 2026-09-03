using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.IO.Pipes;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Automation;

namespace DesktopBridge.UIA3
{
    public class Program
    {
        public const string ProtocolVersion = "1.0";
        public const string SidecarVersion = "1.1.0";
        private static readonly JavaScriptSerializer Serializer = new JavaScriptSerializer();

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
            object id = null;
            string method = "";
            Dictionary<string, object> parameters = null;

            try
            {
                Dictionary<string, object> request = Serializer.Deserialize<Dictionary<string, object>>(rawJson);
                if (request != null)
                {
                    if (request.ContainsKey("id")) id = request["id"];
                    if (request.ContainsKey("method")) method = Convert.ToString(request["method"]);
                    if (request.ContainsKey("params") && request["params"] is Dictionary<string, object>)
                    {
                        parameters = (Dictionary<string, object>)request["params"];
                    }
                }
            }
            catch (Exception ex)
            {
                return SerializeError(id, -32700, "Parse error: " + ex.Message);
            }

            try
            {
                if (method == "handshake")
                {
                    var result = new Dictionary<string, object>
                    {
                        { "protocol_version", ProtocolVersion },
                        { "sidecar_version", SidecarVersion },
                        { "status", "READY" },
                        { "apartment_state", "MTA" },
                        { "capabilities", new string[] { "UIA3_CACHE_REQUEST", "WINDOW_ROOT", "CHILD_ENUMERATION", "SUPPORTED_PATTERNS" } }
                    };
                    return SerializeResult(id, result);
                }
                else if (method == "ping")
                {
                    return SerializeResult(id, new Dictionary<string, object> { { "pong", true } });
                }
                else if (method == "health")
                {
                    long mem = GC.GetTotalMemory(false);
                    var result = new Dictionary<string, object>
                    {
                        { "status", "HEALTHY" },
                        { "memory_bytes", mem },
                        { "thread_id", Thread.CurrentThread.ManagedThreadId }
                    };
                    return SerializeResult(id, result);
                }
                else if (method == "shutdown")
                {
                    shouldExit = true;
                    return SerializeResult(id, new Dictionary<string, object> { { "acknowledged", true } });
                }
                else if (method == "get_window_root")
                {
                    IntPtr hwnd = ExtractHwnd(parameters);
                    if (hwnd == IntPtr.Zero)
                    {
                        return SerializeError(id, -32602, "Invalid or missing 'hwnd' parameter.");
                    }
                    var rootDto = GetWindowRoot(hwnd);
                    return SerializeResult(id, rootDto);
                }
                else if (method == "find_children")
                {
                    IntPtr hwnd = ExtractHwnd(parameters);
                    if (hwnd == IntPtr.Zero)
                    {
                        return SerializeError(id, -32602, "Invalid or missing 'hwnd' parameter.");
                    }
                    int maxDepth = 2;
                    if (parameters != null && parameters.ContainsKey("max_depth"))
                    {
                        int.TryParse(Convert.ToString(parameters["max_depth"]), out maxDepth);
                    }
                    if (maxDepth < 1) maxDepth = 1;
                    if (maxDepth > 5) maxDepth = 5;

                    bool useCache = true;
                    if (parameters != null && parameters.ContainsKey("use_cache"))
                    {
                        bool.TryParse(Convert.ToString(parameters["use_cache"]), out useCache);
                    }

                    var children = FindChildren(hwnd, maxDepth, useCache);
                    return SerializeResult(id, children);
                }
                else if (method == "read_properties")
                {
                    IntPtr hwnd = ExtractHwnd(parameters);
                    string autoId = (parameters != null && parameters.ContainsKey("automation_id")) ? Convert.ToString(parameters["automation_id"]) : null;
                    var props = ReadProperties(hwnd, autoId);
                    return SerializeResult(id, props);
                }
                else if (method == "read_supported_patterns")
                {
                    IntPtr hwnd = ExtractHwnd(parameters);
                    string autoId = (parameters != null && parameters.ContainsKey("automation_id")) ? Convert.ToString(parameters["automation_id"]) : null;
                    var patterns = ReadSupportedPatterns(hwnd, autoId);
                    return SerializeResult(id, patterns);
                }
                else
                {
                    return SerializeError(id, -32601, "Method not found: " + method);
                }
            }
            catch (Exception ex)
            {
                return SerializeError(id, -32603, "Internal error: " + ex.Message);
            }
        }

        private static IntPtr ExtractHwnd(Dictionary<string, object> parameters)
        {
            if (parameters == null || !parameters.ContainsKey("hwnd")) return IntPtr.Zero;
            object val = parameters["hwnd"];
            if (val is int) return new IntPtr((int)val);
            if (val is long) return new IntPtr((long)val);
            string str = Convert.ToString(val);
            if (str.StartsWith("0x", StringComparison.OrdinalIgnoreCase))
            {
                long hexVal;
                if (long.TryParse(str.Substring(2), System.Globalization.NumberStyles.HexNumber, null, out hexVal))
                {
                    return new IntPtr(hexVal);
                }
            }
            long parsed;
            if (long.TryParse(str, out parsed))
            {
                return new IntPtr(parsed);
            }
            return IntPtr.Zero;
        }

        private static Dictionary<string, object> GetWindowRoot(IntPtr hwnd)
        {
            try
            {
                AutomationElement el = AutomationElement.FromHandle(hwnd);
                if (el == null) return null;
                return MapElementToDto(el, 0);
            }
            catch (Exception ex)
            {
                var err = new Dictionary<string, object>();
                err["error"] = ex.Message;
                err["hwnd"] = hwnd.ToInt64();
                return err;
            }
        }

        private static List<Dictionary<string, object>> FindChildren(IntPtr hwnd, int maxDepth, bool useCache)
        {
            var results = new List<Dictionary<string, object>>();
            try
            {
                AutomationElement root = AutomationElement.FromHandle(hwnd);
                if (root == null) return results;

                if (useCache)
                {
                    CacheRequest cr = new CacheRequest();
                    cr.Add(AutomationElement.AutomationIdProperty);
                    cr.Add(AutomationElement.NameProperty);
                    cr.Add(AutomationElement.ClassNameProperty);
                    cr.Add(AutomationElement.ControlTypeProperty);
                    cr.Add(AutomationElement.BoundingRectangleProperty);
                    cr.Add(AutomationElement.IsEnabledProperty);
                    cr.Add(AutomationElement.IsOffscreenProperty);
                    cr.TreeScope = TreeScope.Element | TreeScope.Descendants;

                    using (cr.Activate())
                    {
                        // Enumerate with TreeWalker within cache context
                        TreeWalker walker = TreeWalker.ControlViewWalker;
                        WalkChildrenCached(root, walker, 1, maxDepth, results);
                    }
                }
                else
                {
                    TreeWalker walker = TreeWalker.ControlViewWalker;
                    WalkChildrenLive(root, walker, 1, maxDepth, results);
                }
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine("[Sidecar] FindChildren exception: " + ex.Message);
            }
            return results;
        }

        private static void WalkChildrenCached(AutomationElement parent, TreeWalker walker, int currentDepth, int maxDepth, List<Dictionary<string, object>> results)
        {
            if (parent == null || currentDepth > maxDepth) return;

            AutomationElement child = null;
            try
            {
                child = walker.GetFirstChild(parent);
            }
            catch { }

            int siblings = 0;
            while (child != null && siblings < 100) // bounded traversal safety limit
            {
                siblings++;
                try
                {
                    var dto = MapElementToDto(child, currentDepth);
                    if (dto != null)
                    {
                        results.Add(dto);
                    }
                }
                catch { }

                if (currentDepth < maxDepth)
                {
                    WalkChildrenCached(child, walker, currentDepth + 1, maxDepth, results);
                }

                try
                {
                    child = walker.GetNextSibling(child);
                }
                catch
                {
                    break;
                }
            }
        }

        private static void WalkChildrenLive(AutomationElement parent, TreeWalker walker, int currentDepth, int maxDepth, List<Dictionary<string, object>> results)
        {
            if (parent == null || currentDepth > maxDepth) return;

            AutomationElement child = null;
            try
            {
                child = walker.GetFirstChild(parent);
            }
            catch { }

            int siblings = 0;
            while (child != null && siblings < 100)
            {
                siblings++;
                try
                {
                    var dto = MapElementToDto(child, currentDepth);
                    if (dto != null)
                    {
                        results.Add(dto);
                    }
                }
                catch { }

                if (currentDepth < maxDepth)
                {
                    WalkChildrenLive(child, walker, currentDepth + 1, maxDepth, results);
                }

                try
                {
                    child = walker.GetNextSibling(child);
                }
                catch
                {
                    break;
                }
            }
        }

        private static Dictionary<string, object> MapElementToDto(AutomationElement el, int depth)
        {
            if (el == null) return null;
            var dto = new Dictionary<string, object>();
            dto["depth"] = depth;

            try
            {
                string autoId = el.Current.AutomationId;
                dto["automation_id"] = autoId ?? "";
            }
            catch { dto["automation_id"] = ""; }

            try
            {
                string name = el.Current.Name;
                dto["name"] = name ?? "";
            }
            catch { dto["name"] = ""; }

            try
            {
                string cls = el.Current.ClassName;
                dto["class_name"] = cls ?? "";
            }
            catch { dto["class_name"] = ""; }

            try
            {
                ControlType ct = el.Current.ControlType;
                dto["control_type"] = (ct != null) ? ct.ProgrammaticName.Replace("ControlType.", "") : "Unknown";
            }
            catch { dto["control_type"] = "Unknown"; }

            try
            {
                var rect = el.Current.BoundingRectangle;
                var boundsDict = new Dictionary<string, object>
                {
                    { "x", (int)rect.X },
                    { "y", (int)rect.Y },
                    { "width", (int)rect.Width },
                    { "height", (int)rect.Height },
                    { "left", (int)rect.Left },
                    { "top", (int)rect.Top },
                    { "right", (int)rect.Right },
                    { "bottom", (int)rect.Bottom }
                };
                dto["bounds"] = boundsDict;
            }
            catch
            {
                dto["bounds"] = new Dictionary<string, object> { { "x", 0 }, { "y", 0 }, { "width", 0 }, { "height", 0 } };
            }

            try
            {
                dto["is_enabled"] = el.Current.IsEnabled;
            }
            catch { dto["is_enabled"] = true; }

            try
            {
                dto["is_offscreen"] = el.Current.IsOffscreen;
            }
            catch { dto["is_offscreen"] = false; }

            try
            {
                dto["hwnd"] = el.Current.NativeWindowHandle;
            }
            catch { dto["hwnd"] = 0; }

            // Supported patterns check
            dto["supported_patterns"] = GetSupportedPatterns(el);

            return dto;
        }

        private static List<string> GetSupportedPatterns(AutomationElement el)
        {
            var patterns = new List<string>();
            if (el == null) return patterns;

            TryPattern(el, InvokePattern.Pattern, "Invoke", patterns);
            TryPattern(el, ValuePattern.Pattern, "Value", patterns);
            TryPattern(el, TogglePattern.Pattern, "Toggle", patterns);
            TryPattern(el, SelectionItemPattern.Pattern, "SelectionItem", patterns);
            TryPattern(el, SelectionPattern.Pattern, "Selection", patterns);
            TryPattern(el, ExpandCollapsePattern.Pattern, "ExpandCollapse", patterns);
            TryPattern(el, ScrollPattern.Pattern, "Scroll", patterns);
            TryPattern(el, WindowPattern.Pattern, "Window", patterns);

            return patterns;
        }

        private static void TryPattern(AutomationElement el, AutomationPattern pattern, string name, List<string> patterns)
        {
            try
            {
                object p = null;
                if (el.TryGetCurrentPattern(pattern, out p) && p != null)
                {
                    patterns.Add(name);
                }
            }
            catch { }
        }

        private static Dictionary<string, object> ReadProperties(IntPtr hwnd, string automationId)
        {
            var res = new Dictionary<string, object>();
            try
            {
                AutomationElement root = AutomationElement.FromHandle(hwnd);
                if (root == null) return res;

                AutomationElement target = root;
                if (!string.IsNullOrEmpty(automationId))
                {
                    target = root.FindFirst(TreeScope.Descendants, new PropertyCondition(AutomationElement.AutomationIdProperty, automationId));
                }

                if (target != null)
                {
                    return MapElementToDto(target, 0);
                }
            }
            catch (Exception ex)
            {
                res["error"] = ex.Message;
            }
            return res;
        }

        private static List<string> ReadSupportedPatterns(IntPtr hwnd, string automationId)
        {
            try
            {
                AutomationElement root = AutomationElement.FromHandle(hwnd);
                if (root == null) return new List<string>();

                AutomationElement target = root;
                if (!string.IsNullOrEmpty(automationId))
                {
                    target = root.FindFirst(TreeScope.Descendants, new PropertyCondition(AutomationElement.AutomationIdProperty, automationId));
                }

                if (target != null)
                {
                    return GetSupportedPatterns(target);
                }
            }
            catch { }
            return new List<string>();
        }

        private static string SerializeResult(object id, object result)
        {
            var dict = new Dictionary<string, object>
            {
                { "jsonrpc", "2.0" },
                { "id", id },
                { "result", result }
            };
            return Serializer.Serialize(dict);
        }

        private static string SerializeError(object id, int code, string message)
        {
            var errorObj = new Dictionary<string, object>
            {
                { "code", code },
                { "message", message }
            };
            var dict = new Dictionary<string, object>
            {
                { "jsonrpc", "2.0" },
                { "id", id },
                { "error", errorObj }
            };
            return Serializer.Serialize(dict);
        }
    }
}
