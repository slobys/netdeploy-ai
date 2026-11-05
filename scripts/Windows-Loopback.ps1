function Test-NetDeployPortAvailable {
    param([int]$Port = 8787)

    $socket = [System.Net.Sockets.Socket]::new(
        [System.Net.Sockets.AddressFamily]::InterNetwork,
        [System.Net.Sockets.SocketType]::Stream,
        [System.Net.Sockets.ProtocolType]::Tcp
    )
    try {
        # Test the same IPv4 address the panel will bind, independent of CIM's listener list.
        $socket.ExclusiveAddressUse = $true
        $socket.Bind([System.Net.IPEndPoint]::new([System.Net.IPAddress]::Loopback, $Port))
        return $true
    } catch [System.Net.Sockets.SocketException] {
        if ($_.Exception.SocketErrorCode -in 'AddressAlreadyInUse', 'AccessDenied') {
            return $false
        }
        throw
    } finally {
        $socket.Dispose()
    }
}
