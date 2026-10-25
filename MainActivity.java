package com.gateprep.app;

import android.app.Activity;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.view.View;
import android.graphics.Color;
import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

public class MainActivity extends Activity {
    private WebView webView;
    private LinearLayout root;
    private TextView status;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private boolean serverReady = false;

    @Override public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.WHITE);
        status = new TextView(this);
        status.setText("Starting GATE Prep…\nPreparing your offline study database.");
        status.setTextSize(18);
        status.setPadding(32, 48, 32, 24);
        root.addView(status, new LinearLayout.LayoutParams(-1, -2));
        ProgressBar progress = new ProgressBar(this);
        root.addView(progress, new LinearLayout.LayoutParams(-2, -2));
        setContentView(root);

        new Thread(() -> {
            try {
                if (!Python.isStarted()) Python.start(new AndroidPlatform(this));
                PyObject module = Python.getInstance().getModule("android_server");
                PyObject result = module.callAttr("start_server", getFilesDir().getAbsolutePath());
                serverReady = true;
                handler.post(() -> showWebView());
            } catch (Throwable e) {
                String msg = e.getClass().getSimpleName() + ": " + e.getMessage();
                handler.post(() -> status.setText("Could not start GATE Prep.\n\n" + msg + "\n\nPlease send this error to support."));
            }
        }, "gate-python-startup").start();
    }

    private void showWebView() {
        root.removeAllViews();
        webView = new WebView(this);
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        webView.setWebViewClient(new WebViewClient());
        webView.setWebChromeClient(new WebChromeClient());
        root.addView(webView, new LinearLayout.LayoutParams(-1, -1));
        setContentView(root);
        webView.loadUrl("http://127.0.0.1:5000/");
    }

    @Override public void onBackPressed() {
        if (webView != null && webView.canGoBack()) webView.goBack();
        else super.onBackPressed();
    }

    @Override protected void onDestroy() {
        if (webView != null) webView.destroy();
        super.onDestroy();
    }
}
