<?php

use App\Http\Controllers\SearchController;
use App\Http\Controllers\AdminController;
use Illuminate\Support\Facades\Route;

// --- Public Routes ---
Route::get('/', [SearchController::class, 'index'])->name('search');
Route::post('/search', [SearchController::class, 'store'])->name('search.store');
Route::get('/jobs/{jobId}', [SearchController::class, 'job'])->name('jobs.show');

// --- Admin Auth (Public) ---
Route::post('/admin/login', [AdminController::class, 'login'])->name('admin.login');
Route::post('/admin/logout', [AdminController::class, 'logout'])->name('admin.logout');

// --- Protected Admin API ---
Route::prefix('admin')->middleware('web')->group(function () {
    // We use a custom middleware closure to check the session
    Route::get('/stats', function () {
        if (!session('minitron_admin')) return response()->json(['error' => 'Unauthorized'], 401);
        return app(AdminController::class)->stats();
    })->name('admin.stats');

    Route::post('/selenium/update', function () {
        if (!session('minitron_admin')) return response()->json(['error' => 'Unauthorized'], 401);
        return app(AdminController::class)->seleniumUpdate();
    })->name('admin.selenium');

    Route::post('/cdata/monitor', function (Request $request) {
        if (!session('minitron_admin')) return response()->json(['error' => 'Unauthorized'], 401);
        return app(AdminController::class)->cdataMonitor($request);
    })->name('admin.cdata');

    Route::post('/diameter/session', function (Request $request) {
        if (!session('minitron_admin')) return response()->json(['error' => 'Unauthorized'], 401);
        return app(AdminController::class)->setDiameterSession($request);
    })->name('admin.diameter');
});
