<?php

namespace App\Http\Controllers;

use App\Services\MinitronApiClient;
use Illuminate\Http\Request;

class AdminController extends Controller
{
    public function __construct(protected MinitronApiClient $api) {}

    public function login(Request $request)
    {
        $password = $request->input('password');
        if ($password === 'admin4231') {
            session(['minitron_admin' => true]);
            return redirect()->back();
        }
        return redirect()->back()->with('error', 'Invalid password');
    }

    public function logout()
    {
        session()->forget('minitron_admin');
        return redirect()->back();
    }

    public function stats()
    {
        return response()->json($this->api->stats());
    }

    public function seleniumUpdate()
    {
        return response()->json($this->api->triggerSeleniumUpdate());
    }

    public function cdataMonitor(Request $request)
    {
        $request->validate(['olt_id' => 'required|string']);
        return response()->json($this->api->triggerCdataMonitor($request->input('olt_id')));
    }

    public function setDiameterSession(Request $request)
    {
        $request->validate(['phpsessid' => 'required|string']);
        // Store in the user's session ONLY, do not write to global file
        session(['diameter_session' => $request->input('phpsessid')]);
        return response()->json(['status' => 'updated', 'session_id_prefix' => substr($request->input('phpsessid'), 0, 20) . '...']);
    }
}
