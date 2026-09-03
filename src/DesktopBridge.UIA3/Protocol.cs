using System;

namespace DesktopBridge.UIA3
{
    public class JsonRpcRequest
    {
        public string jsonrpc { get; set; }
        public string id { get; set; }
        public string method { get; set; }
        public object params_data { get; set; }

        public JsonRpcRequest()
        {
            jsonrpc = "2.0";
            id = string.Empty;
            method = string.Empty;
        }
    }

    public class JsonRpcResponse
    {
        public string jsonrpc { get; set; }
        public string id { get; set; }
        public object result { get; set; }
        public JsonRpcError error { get; set; }

        public JsonRpcResponse()
        {
            jsonrpc = "2.0";
        }
    }

    public class JsonRpcError
    {
        public int code { get; set; }
        public string message { get; set; }

        public JsonRpcError(int code, string message)
        {
            this.code = code;
            this.message = message;
        }
    }
}
