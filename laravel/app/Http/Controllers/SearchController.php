<?php
namespace App\Http\Controllers;

use App\Services\MinitronApiClient;
use Illuminate\Http\Request;

class SearchController extends Controller
{
    public function __construct(protected MinitronApiClient $api) {}

    public function index() { return view('search'); }

    public function store(Request $request)
    {
        $request->validate(['query' => 'required|string|max:255']);
        $sid = session('diameter_session', '');
        return response()->json($this->api->search($request->input('query'), $sid));
    }

    public function job(string $jobId)
    {
        return response()->json($this->api->getJob($jobId));
    }
}
