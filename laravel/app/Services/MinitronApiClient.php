<?php

namespace App\Services;

use Illuminate\Support\Facades\Http;

class MinitronApiClient
{
    protected string $baseUrl;

    public function __construct()
    {
        $this->baseUrl = rtrim(config('services.minitron.url', 'http://127.0.0.1:8001'), '/');
    }

    public function search(string $query, string $sessionId = ''): array
    {
        return Http::timeout(10)->post("{$this->baseUrl}/api/search", [
            'query' => $query, 'session_id' => $sessionId,
        ])->throw()->json();
    }

    public function getJob(string $jobId): array
    {
        return Http::timeout(10)->get("{$this->baseUrl}/api/jobs/{$jobId}")->throw()->json();
    }

    public function stats(): array
    {
        return Http::timeout(10)->get("{$this->baseUrl}/api/stats")->throw()->json();
    }

    public function triggerSeleniumUpdate(): array
    {
        return Http::timeout(10)->post("{$this->baseUrl}/api/selenium/update")->throw()->json();
    }

    public function triggerCdataMonitor(string $oltId, ?array $ports = null): array
    {
        return Http::timeout(10)->post("{$this->baseUrl}/api/cdata/monitor", [
            'olt_id' => $oltId, 'ports' => $ports,
        ])->throw()->json();
    }

    public function setDiameterSession(string $phpsessid): array
    {
        return Http::timeout(10)->post("{$this->baseUrl}/api/diameter/session", [
            'phpsessid' => $phpsessid,
        ])->throw()->json();
    }
}
