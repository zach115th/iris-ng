/* IRIS's theme behaviours: the navigation togglers, the quick sidebar, the minimized sidebar's hover and the sidebar's
 * submenus (Phase 5 slice 5.0, replacing the Atlantis theme's atlantis.min.js - ThemeKita, 2018 - whose other
 * handlers bound to nothing IRIS renders).
 *
 * What changed against atlantis.min.js:
 *   - the sidebar and the quick actions list scroll natively; jquery.scrollbar (and the jQuery UI draggable it gave
 *     its bars) is gone, its styles in css/iris-theme.css replaced by native scrollbars;
 *   - the sidenav toggler marks itself .toggled (atlantis marked the quick sidebar's toggler: the two handlers
 *     shared one variable); no stylesheet styles .toggled on either;
 *   - the quick sidebar's toggler reads the quick sidebar's own state (atlantis read the nav's, so with the nav open
 *     on a narrow screen the quick sidebar would not open).
 * As before, a click anywhere in .wrapper outside the quick sidebar closes it, and that mouseup runs before the
 * toggler's click: the toggler opens the quick sidebar, its close button or a click elsewhere closes it.
 */
'use strict';

$(function () {
    // atlantis.min.js ran its body in a ready callback nested in another one: kept, so the handlers below bind at
    // the same moment as before - after every ready callback the page registered at load - and reach the same
    // elements (they bind to what exists then, not by delegation)
    $(function () {
        var $html = $('html');

        var navOpen = false;
        var $sidenavToggler = $('.sidenav-toggler');
        $sidenavToggler.on('click', function () {
            navOpen = !navOpen;
            $html.toggleClass('nav_open', navOpen);
            $sidenavToggler.toggleClass('toggled', navOpen);
        });

        var quickOpen = false;
        var $quickToggler = $('.quick-sidebar-toggler');
        var closeQuickSidebar = function () {
            $html.removeClass('quick_sidebar_open');
            $quickToggler.removeClass('toggled');
            quickOpen = false;
        };
        $quickToggler.on('click', function () {
            if (quickOpen) {
                closeQuickSidebar();
            } else {
                $html.addClass('quick_sidebar_open');
                $quickToggler.addClass('toggled');
                quickOpen = true;
            }
        });
        $('.wrapper').on('mouseup', function (e) {
            var $quick = $('.quick-sidebar');
            if (e.target.className === $quick.attr('class') || $quick.has(e.target).length) {
                return;
            }
            closeQuickSidebar();
        });
        $('.close-quick-sidebar').on('click', closeQuickSidebar);

        var topbarOpen = false;
        var $topbarToggler = $('.topbar-toggler');
        $topbarToggler.on('click', function () {
            topbarOpen = !topbarOpen;
            $html.toggleClass('topbar_open', topbarOpen);
            $topbarToggler.toggleClass('toggled', topbarOpen);
        });

        // the minimized sidebar opens while the mouse is over it (IRIS's .toggle-sidebar, in common.js, minimizes it)
        $('.sidebar').on('mouseenter', function () {
            if ($('.wrapper').hasClass('sidebar_minimize')) {
                $('.wrapper').addClass('sidebar_minimize_hover');
            }
        }).on('mouseleave', function () {
            if ($('.wrapper').hasClass('sidebar_minimize')) {
                $('.wrapper').removeClass('sidebar_minimize_hover');
            }
        });

        // a nav item whose collapse is about to open is marked .submenu (read before Bootstrap's own click handler,
        // which is delegated from the document, toggles the collapse)
        $('.nav-item a').on('click', function () {
            var $item = $(this).parent();
            if ($item.find('.collapse').hasClass('show')) {
                $item.removeClass('submenu');
            } else {
                $item.addClass('submenu');
            }
        });
    });
});
