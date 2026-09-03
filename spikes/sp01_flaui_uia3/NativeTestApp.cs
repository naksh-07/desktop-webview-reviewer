using System;
using System.Drawing;
using System.Threading;
using System.Windows.Forms;

namespace Spike01
{
    public class NativeTestApp : Form
    {
        private TabControl tabControl;
        private TabPage tabSmall;
        private TabPage tabMedium;
        private TabPage tabLarge;

        // Dynamic controls for staleness testing
        private Panel dynamicPanel;
        private Button dynamicButton;
        private ListBox dynamicList;
        private int dynamicCounter = 0;

        // Status
        private Label lblStatus;

        public NativeTestApp()
        {
            this.Text = "Spike01_NativeTestApp";
            this.Size = new Size(800, 600);
            this.StartPosition = FormStartPosition.CenterScreen;

            InitializeComponents();
        }

        private void InitializeComponents()
        {
            tabControl = new TabControl();
            tabControl.Dock = DockStyle.Fill;

            // 1. Small Tree (~10 controls)
            tabSmall = new TabPage("Small Tree");
            BuildSmallTree(tabSmall);
            tabControl.TabPages.Add(tabSmall);

            // 2. Medium Tree (~100 controls)
            tabMedium = new TabPage("Medium Tree");
            BuildMediumTree(tabMedium);
            tabControl.TabPages.Add(tabMedium);

            // 3. Large Tree (~500 controls)
            tabLarge = new TabPage("Large Tree");
            BuildLargeTree(tabLarge);
            tabControl.TabPages.Add(tabLarge);

            // Dynamic panel at bottom for mutation and testing
            Panel bottomPanel = new Panel();
            bottomPanel.Dock = DockStyle.Bottom;
            bottomPanel.Height = 120;

            lblStatus = new Label();
            lblStatus.Text = "Status: Ready";
            lblStatus.Location = new Point(10, 10);
            lblStatus.AutoSize = true;
            bottomPanel.Controls.Add(lblStatus);

            dynamicPanel = new Panel();
            dynamicPanel.Name = "DynamicHostPanel";
            dynamicPanel.Location = new Point(10, 35);
            dynamicPanel.Size = new Size(200, 40);
            dynamicPanel.BorderStyle = BorderStyle.FixedSingle;

            dynamicButton = new Button();
            dynamicButton.Name = "btn_dynamic_target";
            dynamicButton.Text = "Target Button v0";
            dynamicButton.Location = new Point(5, 5);
            dynamicButton.Size = new Size(180, 28);
            dynamicPanel.Controls.Add(dynamicButton);
            bottomPanel.Controls.Add(dynamicPanel);

            // Mutate button
            Button btnMutate = new Button();
            btnMutate.Name = "btn_trigger_mutation";
            btnMutate.Text = "Recreate Target";
            btnMutate.Location = new Point(220, 35);
            btnMutate.Size = new Size(130, 28);
            btnMutate.Click += (s, e) => {
                dynamicCounter++;
                dynamicPanel.Controls.Clear();
                dynamicButton = new Button();
                dynamicButton.Name = "btn_dynamic_target";
                dynamicButton.Text = "Target Button v" + dynamicCounter;
                dynamicButton.Location = new Point(5, 5);
                dynamicButton.Size = new Size(180, 28);
                dynamicPanel.Controls.Add(dynamicButton);
                lblStatus.Text = "Status: Mutated " + dynamicCounter;
            };
            bottomPanel.Controls.Add(btnMutate);

            // Destroy button
            Button btnDestroy = new Button();
            btnDestroy.Name = "btn_trigger_destroy";
            btnDestroy.Text = "Destroy Target";
            btnDestroy.Location = new Point(360, 35);
            btnDestroy.Size = new Size(120, 28);
            btnDestroy.Click += (s, e) => {
                dynamicPanel.Controls.Clear();
                lblStatus.Text = "Status: Destroyed";
            };
            bottomPanel.Controls.Add(btnDestroy);

            // Sleep button (hang simulation)
            Button btnHang = new Button();
            btnHang.Name = "btn_trigger_hang";
            btnHang.Text = "Simulate 3s Hang";
            btnHang.Location = new Point(490, 35);
            btnHang.Size = new Size(130, 28);
            btnHang.Click += (s, e) => {
                lblStatus.Text = "Status: Sleeping 3000ms";
                Application.DoEvents();
                Thread.Sleep(3000);
                lblStatus.Text = "Status: Resumed";
            };
            bottomPanel.Controls.Add(btnHang);

            // High-volume property change
            Button btnSpam = new Button();
            btnSpam.Name = "btn_trigger_spam";
            btnSpam.Text = "Spam 100 Events";
            btnSpam.Location = new Point(630, 35);
            btnSpam.Size = new Size(130, 28);
            btnSpam.Click += (s, e) => {
                for (int i = 0; i < 100; i++)
                {
                    lblStatus.Text = "Event " + i + " at " + DateTime.UtcNow.Ticks;
                    Application.DoEvents();
                }
                lblStatus.Text = "Status: Spam Complete";
            };
            btnSpam.AccessibleName = "btn_trigger_spam";
            bottomPanel.Controls.Add(btnSpam);

            btnMutate.AccessibleName = "btn_trigger_mutation";
            btnDestroy.AccessibleName = "btn_trigger_destroy";
            btnHang.AccessibleName = "btn_trigger_hang";
            dynamicButton.AccessibleName = "btn_dynamic_target";

            this.Controls.Add(bottomPanel);
            this.Controls.Add(tabControl);
            bottomPanel.BringToFront();
        }

        private void BuildSmallTree(TabPage page)
        {
            Panel p = new Panel { Dock = DockStyle.Fill, AutoScroll = true };
            for (int i = 0; i < 5; i++)
            {
                Button btn = new Button {
                    Name = "btn_small_" + i,
                    Text = "Small Button " + i,
                    Location = new Point(20, 20 + i * 35),
                    Size = new Size(150, 28)
                };
                p.Controls.Add(btn);

                TextBox txt = new TextBox {
                    Name = "txt_small_" + i,
                    Text = "Input " + i,
                    Location = new Point(190, 20 + i * 35),
                    Size = new Size(150, 24)
                };
                p.Controls.Add(txt);
            }
            page.Controls.Add(p);
        }

        private void BuildMediumTree(TabPage page)
        {
            Panel p = new Panel { Dock = DockStyle.Fill, AutoScroll = true };
            int y = 10;
            // 5 groups of 20 elements = 100 elements
            for (int g = 0; g < 5; g++)
            {
                GroupBox gb = new GroupBox {
                    Name = "group_med_" + g,
                    Text = "Category " + g,
                    Location = new Point(10, y),
                    Size = new Size(740, 100)
                };
                for (int i = 0; i < 9; i++)
                {
                    Button b = new Button {
                        Name = string.Format("btn_med_{0}_{1}", g, i),
                        Text = string.Format("G{0}-B{1}", g, i),
                        Location = new Point(15 + i * 78, 20),
                        Size = new Size(72, 26)
                    };
                    gb.Controls.Add(b);

                    TextBox t = new TextBox {
                        Name = string.Format("txt_med_{0}_{1}", g, i),
                        Text = string.Format("Val {0}", i),
                        Location = new Point(15 + i * 78, 55),
                        Size = new Size(72, 22)
                    };
                    gb.Controls.Add(t);
                }
                p.Controls.Add(gb);
                y += 110;
            }
            page.Controls.Add(p);
        }

        private void BuildLargeTree(TabPage page)
        {
            Panel p = new Panel { Dock = DockStyle.Fill, AutoScroll = true };
            int y = 10;
            // 20 panels each with 25 controls = 500 controls
            for (int g = 0; g < 20; g++)
            {
                Panel container = new Panel {
                    Name = "panel_large_" + g,
                    Location = new Point(10, y),
                    Size = new Size(740, 60),
                    BorderStyle = BorderStyle.FixedSingle
                };

                for (int i = 0; i < 12; i++)
                {
                    Label lbl = new Label {
                        Name = string.Format("lbl_large_{0}_{1}", g, i),
                        Text = string.Format("L{0}.{1}", g, i),
                        Location = new Point(5 + i * 60, 5),
                        Size = new Size(55, 18)
                    };
                    container.Controls.Add(lbl);

                    Button b = new Button {
                        Name = string.Format("btn_large_{0}_{1}", g, i),
                        Text = string.Format("B{0}", i),
                        Location = new Point(5 + i * 60, 25),
                        Size = new Size(55, 24)
                    };
                    container.Controls.Add(b);
                }
                p.Controls.Add(container);
                y += 70;
            }
            page.Controls.Add(p);
        }

        [STAThread]
        public static void Main(string[] args)
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new NativeTestApp());
        }
    }
}
